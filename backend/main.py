"""
Bella Vista backend.

Two operating modes, controlled by BELLA_VISTA_MODE:

  live  (default) - user requests are sent to the OpenAI Responses API with the
                     hosted `web_search` tool. Real, current listings are
                     searched, normalized into Bella Vista's Product schema and
                     persisted so real price history can be built over time.
                     If no OPENAI_API_KEY is configured, or the OpenAI call
                     fails, requests transparently fall back to demo mode and
                     the response says so (fallback_available=True) - nothing
                     ever crashes the frontend.

  demo  - uses the original local, deterministic 72-item seeded catalog. Useful
          for demos when a live API key isn't available. Demo data is clearly
          marked (`source: "demo"`) and never mixed with unverified "real"
          price history claims.

Every product returned by the API - live or demo - conforms to the same
Product schema so the frontend only needs one type.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:  # dotenv is a convenience, not a hard requirement
    pass

try:
    from openai import OpenAI, RateLimitError
except ImportError:  # openai SDK not installed -> live mode auto-falls back
    OpenAI = None  # type: ignore[assignment]
    RateLimitError = None  # type: ignore[assignment,misc]

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

DB_PATH = Path(__file__).with_name("bella_vista.db")

app = FastAPI(title="Bella Vista API", version="3.0.0")

# CORS: allow_origins=["*"] is convenient for local dev but not safe to ship.
# Set BELLA_VISTA_ALLOWED_ORIGINS to a comma-separated list of real frontend
# origins in production (e.g. "https://bellavista.app,https://www.bellavista.app").
# Falls back to the default Vite dev server origins when unset, NOT to "*".
_default_dev_origins = "http://localhost:5173,http://127.0.0.1:5173"
_allowed_origins_env = os.getenv("BELLA_VISTA_ALLOWED_ORIGINS", "").strip()
if _allowed_origins_env == "*":
    ALLOWED_ORIGINS = ["*"]
elif _allowed_origins_env:
    ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
else:
    ALLOWED_ORIGINS = _default_dev_origins.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

BELLA_VISTA_MODE = os.getenv("BELLA_VISTA_MODE", "live").strip().lower()
if BELLA_VISTA_MODE not in ("live", "demo"):
    BELLA_VISTA_MODE = "live"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

OPENAI_CLIENT = None
if BELLA_VISTA_MODE == "live" and OpenAI and OPENAI_API_KEY:
    OPENAI_CLIENT = OpenAI(api_key=OPENAI_API_KEY)

# A search result stays "fresh" for this long before we allow another price
# observation for the same product to be written (avoids spamming the price
# history table every time the exact same product resurfaces in a search).
PRICE_OBSERVATION_WINDOW_HOURS = 6

# How long a completed live search result is reused for an identical
# query+intent before we're willing to call OpenAI again for it.
SEARCH_CACHE_TTL_MINUTES = int(os.getenv("BELLA_VISTA_SEARCH_CACHE_TTL_MINUTES", "15"))

# search_sessions/search_products/price_history rows older than this are
# pruned on startup so the DB doesn't grow unbounded. price_history gets a
# longer window since buy recommendations depend on having real history.
SEARCH_SESSION_RETENTION_DAYS = int(os.getenv("BELLA_VISTA_SESSION_RETENTION_DAYS", "30"))
PRICE_HISTORY_RETENTION_DAYS = int(os.getenv("BELLA_VISTA_PRICE_HISTORY_RETENTION_DAYS", "180"))

# Opt-in stricter image URL validation (HEAD request + content-type check).
# Off by default: it adds a network round trip per product on every live
# search, which is a real latency cost. Turn on if broken images are a
# bigger problem in practice than slower searches.
VALIDATE_IMAGE_URLS = os.getenv("BELLA_VISTA_VALIDATE_IMAGE_URLS", "false").strip().lower() == "true"

# --------------------------------------------------------------------------
# Demo catalog (kept as an offline fallback / quick-demo dataset)
# --------------------------------------------------------------------------

COLORS = ["red", "white", "black", "blue", "gold", "green", "grey", "cream", "pink", "orange"]
BRANDS = ["Nike", "Adidas", "Puma", "New Balance", "Reebok", "Vans", "Converse", "Asics"]
STYLES = ["sporty", "casual", "chunky", "minimal", "retro", "running", "streetwear", "classic"]
IMAGE_PATHS = {
    "red-white-gold": "/images/red-white-gold/red-white-gold.jpg",
    "black-chunky-white": "/images/black-chunky-white/black-chunky-white.jpg",
    "blue-college": "/images/blue-college/blue-college.jpg",
    "neutral-everyday": "/images/neutral-everyday/neutral-everyday.jpg",
}


def image_path(colors: list[str], style: str) -> str:
    color_set = set(colors)
    if style == "chunky":
        return IMAGE_PATHS["black-chunky-white"]
    if "blue" in color_set:
        return IMAGE_PATHS["blue-college"]
    if "red" in color_set or "gold" in color_set:
        return IMAGE_PATHS["red-white-gold"]
    if "black" in color_set:
        return IMAGE_PATHS["black-chunky-white"]
    return IMAGE_PATHS["neutral-everyday"]


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = db()
    # --- demo catalog -----------------------------------------------------
    conn.execute(
        """CREATE TABLE IF NOT EXISTS demo_products (
            id INTEGER PRIMARY KEY, name TEXT, brand TEXT, price INTEGER, original_price INTEGER,
            colors TEXT, style TEXT, category TEXT, description TEXT, image TEXT, rating REAL
        )"""
    )
    # --- live product cache -------------------------------------------------
    # product_key is a stable hash derived from product_url/name/store so the
    # same real-world product maps to the same row across separate searches.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS live_products (
            product_key TEXT PRIMARY KEY,
            name TEXT, brand TEXT, price REAL, currency TEXT, original_price REAL,
            discount_percent REAL, image_url TEXT, product_url TEXT, store TEXT,
            rating REAL, review_count INTEGER, description TEXT, colors TEXT,
            category TEXT, availability TEXT, source_url TEXT, source_title TEXT,
            created_at TEXT, updated_at TEXT
        )"""
    )
    # --- real, observed price history ---------------------------------------
    conn.execute(
        """CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_key TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT,
            store TEXT,
            observed_at TEXT NOT NULL
        )"""
    )
    # --- search sessions ------------------------------------------------------
    conn.execute(
        """CREATE TABLE IF NOT EXISTS search_sessions (
            id TEXT PRIMARY KEY,
            query TEXT,
            intent_json TEXT,
            mode TEXT,
            created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS search_products (
            search_id TEXT NOT NULL,
            product_key TEXT NOT NULL,
            rank INTEGER,
            PRIMARY KEY (search_id, product_key)
        )"""
    )

    cleanup_old_rows(conn)

    if conn.execute("SELECT COUNT(*) FROM demo_products").fetchone()[0] == 0:
        rows = []
        for i in range(72):
            brand, color, style = BRANDS[i % len(BRANDS)], COLORS[i % len(COLORS)], STYLES[i % len(STYLES)]
            accent = COLORS[(i * 3 + 2) % len(COLORS)]
            price = 2499 + (i * 731) % 8500
            rows.append((
                i + 1, f"{brand} {style.title()} {100 + i}", brand, price, price + 900 + (i % 4) * 500,
                f"{color},{accent}", style, "Sneakers",
                f"A versatile {style} silhouette with {color} and {accent} detailing, built for everyday movement.",
                image_path([color, accent], style),
                round(4.1 + (i % 9) / 10, 1),
            ))
        conn.executemany("INSERT INTO demo_products VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def cleanup_old_rows(conn: sqlite3.Connection) -> None:
    """Bounds table growth. Runs once at startup rather than on a schedule -
    there's no background task runner in this single-process app. For a
    production deployment with a real process manager, move this to a
    periodic cron/beat task instead of (or in addition to) startup."""
    session_cutoff = (datetime.utcnow() - timedelta(days=SEARCH_SESSION_RETENTION_DAYS)).isoformat()
    old_sessions = [
        r["id"] for r in conn.execute(
            "SELECT id FROM search_sessions WHERE created_at < ?", (session_cutoff,)
        ).fetchall()
    ]
    if old_sessions:
        placeholders = ",".join("?" * len(old_sessions))
        conn.execute(f"DELETE FROM search_products WHERE search_id IN ({placeholders})", old_sessions)
        conn.execute(f"DELETE FROM search_sessions WHERE id IN ({placeholders})", old_sessions)

    price_cutoff = (datetime.utcnow() - timedelta(days=PRICE_HISTORY_RETENTION_DAYS)).isoformat()
    conn.execute("DELETE FROM price_history WHERE observed_at < ?", (price_cutoff,))
    conn.commit()


@app.on_event("startup")
def startup() -> None:
    init_db()


# --------------------------------------------------------------------------
# Shared Product schema helpers
# --------------------------------------------------------------------------

def new_product_shell(**overrides: Any) -> dict[str, Any]:
    """The canonical Product shape. Every field defaults to a safe 'unknown' value."""
    base = {
        "id": None,
        "name": None,
        "brand": None,
        "price": None,
        "currency": "INR",
        "original_price": None,
        "discount_percent": None,
        "image_url": None,
        "product_url": None,
        "store": None,
        "rating": None,
        "review_count": None,
        "description": None,
        "colors": [],
        "category": "Sneakers",
        "match_score": None,
        "match_reasons": [],
        "source_url": None,
        "source_title": None,
        "availability": None,
        "price_history": [],
        "buy_recommendation": None,
        "similar_product_ids": [],
        "source": "live",
    }
    base.update(overrides)
    return base


def demo_row_to_product(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    colors = item["colors"].split(",") if item["colors"] else []
    discount = round((1 - item["price"] / item["original_price"]) * 100) if item["original_price"] else 0
    return new_product_shell(
        id=f"demo-{item['id']}",
        name=item["name"],
        brand=item["brand"],
        price=item["price"],
        currency="INR",
        original_price=item["original_price"],
        discount_percent=discount,
        image_url=item["image"],
        product_url=None,
        store="Bella Vista Demo Catalog",
        rating=item["rating"],
        review_count=None,
        description=item["description"],
        colors=colors,
        category=item["category"],
        availability="in_stock",
        source_url=None,
        source_title=None,
        source="demo",
    )


def demo_price_history(product_id: int, current_price: float) -> list[dict[str, Any]]:
    """Deterministic synthetic history for demo mode only - clearly not a live claim."""
    return [
        {
            "date": (date.today() - timedelta(days=30 - i * 5)).isoformat(),
            "price": round(current_price + ((i + product_id) % 3 - 1) * 180),
        }
        for i in range(7)
    ]


# --------------------------------------------------------------------------
# Demo-mode intent parsing + matching (also used as the live-mode fallback)
# --------------------------------------------------------------------------

def local_parse_intent(text: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    state = {**(previous or {}), "product_type": "sneakers"}
    lower = text.lower()
    found_colors = [c for c in COLORS if re.search(rf"\b{c}\b", lower)]
    if found_colors:
        if re.search(r"\b(remove|without|no)\b", lower):
            state["colors"] = [c for c in state.get("colors", []) if c not in found_colors]
        else:
            state["colors"] = list(dict.fromkeys(state.get("colors", []) + found_colors))
    amounts = re.findall(r"(?:under|below|less than|around|budget(?: is)?|₹|rs\.?)\s*[,₹]?\s*(\d[\d,]*)", lower)
    if amounts:
        state["max_price"] = int(amounts[-1].replace(",", ""))
    brands = [b for b in BRANDS if b.lower() in lower]
    if brands:
        state["brand"] = brands[0]
    if re.search(r"\b(any brand|all brands|no brand restriction)\b", lower):
        state.pop("brand", None)
    styles = [s for s in STYLES if s in lower]
    if styles:
        state["style"] = styles[-1]
    if "cheaper" in lower:
        state["cheaper"] = True
        state["max_price"] = state.get("max_price", 6000)
    return state


def match_demo_products(intent: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    conn = db()
    db_rows = conn.execute("SELECT * FROM demo_products").fetchall()
    conn.close()
    scored = []
    wanted = set(intent.get("colors", []))
    style = intent.get("style")
    style = style[0] if isinstance(style, list) and style else style
    for row in db_rows:
        item = demo_row_to_product(row)
        score, reasons = 45, []
        overlap = wanted.intersection(item["colors"])
        if wanted:
            score += 35 * len(overlap) / len(wanted)
            if overlap:
                reasons.append(f"{', '.join(sorted(overlap)).title()} tones")
        if intent.get("max_price"):
            if item["price"] <= intent["max_price"]:
                score += 15
                reasons.append(f"Under ₹{intent['max_price']:,}")
            else:
                score -= min(18, (item["price"] - intent["max_price"]) / 400)
        if intent.get("brand"):
            score += 12 if item["brand"].lower() == intent["brand"].lower() else -8
            if item["brand"].lower() == intent["brand"].lower():
                reasons.append(f"{item['brand']} pick")
        if style and row["style"] == style:
            score += 12
            reasons.append(f"{row['style'].title()} feel")
        if intent.get("cheaper"):
            score += max(0, 10 - item["price"] / 1500)
        item["match_score"] = max(40, min(99, round(score)))
        item["match_reasons"] = reasons or ["Versatile everyday match"]
        scored.append(item)
    return sorted(scored, key=lambda x: (-x["match_score"], x["price"]))[:limit]


# --------------------------------------------------------------------------
# Live mode: OpenAI Responses API + hosted web_search tool
# --------------------------------------------------------------------------

LIVE_SYSTEM_PROMPT = """You are Bella Vista's live sneaker/shoe shopping assistant.

You are given a shopper's natural-language request (and optionally the
previously understood shopping intent, which you should update/merge rather
than discard). Use the web_search tool to find CURRENT, REAL sneaker listings
that match the request, preferring official brand stores and major reputable
retailers (Nike.com, Adidas.com, Myntra, Flipkart, Amazon, official Indian
retailers, etc).

After searching, respond with ONLY a single valid JSON object (no markdown
fences, no commentary) with this exact shape:

{
  "message": "one short, friendly sentence summarizing what you found",
  "intent": {
    "product_type": "sneakers",
    "colors": [],
    "max_price": null,
    "min_price": null,
    "brand": null,
    "style": [],
    "use_case": [],
    "keywords": [],
    "cheaper": false
  },
  "products": [
    {
      "name": "...",
      "brand": "...",
      "price": 5499,
      "currency": "INR",
      "original_price": 6999,
      "image_url": "...",
      "product_url": "...",
      "store": "...",
      "rating": null,
      "review_count": null,
      "description": "...",
      "colors": [],
      "category": "Sneakers",
      "match_reasons": ["..."],
      "source_url": "...",
      "source_title": "...",
      "availability": "in_stock"
    }
  ]
}

CRITICAL DATA-INTEGRITY RULES:
- Never invent a price, image URL, product URL, rating, review count or
  availability. If you cannot verify a field from what you found, set it to
  null (or [] for colors) rather than guessing.
- Only include products you actually found through web search this turn.
- image_url and product_url must be real URLs you found, not constructed
  guesses.
- Return between 4 and 12 products when the search finds enough real
  candidates; fewer is fine if that's all the web search reliably supports.
- Merge the new request into the previous intent when one is supplied,
  updating only what the new message implies (e.g. "make it cheaper" adjusts
  max_price/cheaper, "more sporty" adjusts style, "actually under 7000"
  overwrites max_price).
- Output raw JSON only. No ```json fences, no extra text before or after.
"""


def make_product_key(product_url: str | None, name: str | None, store: str | None) -> str:
    base = f"{product_url or ''}|{(name or '').lower()}|{(store or '').lower()}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


def safe_url(value: Any) -> str | None:
    if isinstance(value, str) and value.strip().lower().startswith(("http://", "https://")):
        return value.strip()
    return None


def validate_image_url(url: str | None, timeout: float = 2.5) -> str | None:
    """Optional stricter check: HEAD the URL and confirm it looks like an
    image before we show it. Only runs when BELLA_VISTA_VALIDATE_IMAGE_URLS=true,
    since it adds a network round trip per product on every live search - a
    real latency cost for a nice-to-have integrity check. On any failure
    (timeout, non-2xx, non-image content-type) we drop the URL to null rather
    than showing a possibly-broken image, consistent with the "null instead
    of a guess" rule elsewhere in this file."""
    if not url or not VALIDATE_IMAGE_URLS:
        return url
    try:
        import urllib.request

        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "BellaVista/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - trusted, http(s)-only via safe_url
            if 200 <= resp.status < 300 and resp.headers.get("Content-Type", "").startswith("image/"):
                return url
    except Exception:  # noqa: BLE001 - any failure means "can't verify it", not "crash the search"
        pass
    return None


def safe_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def safe_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_live_product(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = safe_str(raw.get("name"))
    if not name:
        return None  # a product with no name is not usable

    product_url = safe_url(raw.get("product_url"))
    image_url = validate_image_url(safe_url(raw.get("image_url")))
    store = safe_str(raw.get("store"))
    price = safe_number(raw.get("price"))
    original_price = safe_number(raw.get("original_price"))
    discount_percent = None
    if price is not None and original_price is not None and original_price > 0 and price <= original_price:
        discount_percent = round((1 - price / original_price) * 100)

    key = make_product_key(product_url, name, store)

    return new_product_shell(
        id=key,
        name=name,
        brand=safe_str(raw.get("brand")),
        price=price,
        currency=safe_str(raw.get("currency")) or "INR",
        original_price=original_price,
        discount_percent=discount_percent,
        image_url=image_url,
        product_url=product_url,
        store=store,
        rating=safe_number(raw.get("rating")),
        review_count=int(raw["review_count"]) if isinstance(raw.get("review_count"), (int, float)) else None,
        description=safe_str(raw.get("description")),
        colors=safe_list(raw.get("colors")),
        category=safe_str(raw.get("category")) or "Sneakers",
        match_reasons=safe_list(raw.get("match_reasons")),
        source_url=safe_url(raw.get("source_url")) or product_url,
        source_title=safe_str(raw.get("source_title")),
        availability=safe_str(raw.get("availability")),
        source="live",
    )


def score_against_intent(product: dict[str, Any], intent: dict[str, Any]) -> int:
    """Bella Vista's own relevance score - an opinion, not a fabricated fact."""
    score = 55
    wanted_colors = {c.lower() for c in intent.get("colors", [])}
    have_colors = {c.lower() for c in product.get("colors", [])}
    if wanted_colors:
        overlap = wanted_colors & have_colors
        score += 25 * (len(overlap) / len(wanted_colors)) if overlap else 0
    if intent.get("max_price") and product.get("price") is not None:
        if product["price"] <= intent["max_price"]:
            score += 15
        else:
            score -= min(20, (product["price"] - intent["max_price"]) / 400)
    if intent.get("brand") and product.get("brand"):
        score += 12 if product["brand"].lower() == intent["brand"].lower() else -6
    styles = intent.get("style") or []
    styles = styles if isinstance(styles, list) else [styles]
    if styles and product.get("description"):
        desc = product["description"].lower()
        if any(s.lower() in desc for s in styles):
            score += 8
    return max(5, min(99, round(score)))


def persist_live_products(products: list[dict[str, Any]]) -> None:
    conn = db()
    now = datetime.utcnow().isoformat()
    for p in products:
        conn.execute(
            """INSERT INTO live_products (
                product_key, name, brand, price, currency, original_price, discount_percent,
                image_url, product_url, store, rating, review_count, description, colors,
                category, availability, source_url, source_title, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(product_key) DO UPDATE SET
                name=excluded.name, brand=excluded.brand, price=excluded.price,
                currency=excluded.currency, original_price=excluded.original_price,
                discount_percent=excluded.discount_percent, image_url=excluded.image_url,
                product_url=excluded.product_url, store=excluded.store, rating=excluded.rating,
                review_count=excluded.review_count, description=excluded.description,
                colors=excluded.colors, category=excluded.category, availability=excluded.availability,
                source_url=excluded.source_url, source_title=excluded.source_title,
                updated_at=excluded.updated_at
            """,
            (
                p["id"], p["name"], p["brand"], p["price"], p["currency"], p["original_price"],
                p["discount_percent"], p["image_url"], p["product_url"], p["store"], p["rating"],
                p["review_count"], p["description"], ",".join(p["colors"]), p["category"],
                p["availability"], p["source_url"], p["source_title"], now, now,
            ),
        )
        if p.get("price") is not None:
            record_price_observation(conn, p["id"], p["price"], p["currency"], p["store"])
    conn.commit()
    conn.close()


def record_price_observation(conn: sqlite3.Connection, product_key: str, price: float, currency: str | None, store: str | None) -> None:
    cutoff = (datetime.utcnow() - timedelta(hours=PRICE_OBSERVATION_WINDOW_HOURS)).isoformat()
    recent = conn.execute(
        "SELECT id FROM price_history WHERE product_key = ? AND observed_at >= ? ORDER BY observed_at DESC LIMIT 1",
        (product_key, cutoff),
    ).fetchone()
    if recent:
        return  # already have a fresh-enough observation for this product
    conn.execute(
        "INSERT INTO price_history (product_key, price, currency, store, observed_at) VALUES (?,?,?,?,?)",
        (product_key, price, currency, store, datetime.utcnow().isoformat()),
    )


# --------------------------------------------------------------------------
# Short-TTL cache for identical live searches (query+intent) so reloading or
# two users searching the same thing within a few minutes doesn't re-trigger
# an OpenAI call. In-memory + single-process only; fine for this app's scale,
# but won't share across multiple backend workers/instances - a real
# multi-process deployment would want this in SQLite or a shared cache
# (Redis) instead.
# --------------------------------------------------------------------------
_SEARCH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _search_cache_key(query: str, previous_intent: dict[str, Any] | None) -> str:
    normalized_query = " ".join(query.strip().lower().split())
    normalized_intent = json.dumps(previous_intent or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(f"{normalized_query}|{normalized_intent}".encode("utf-8")).hexdigest()


def _search_cache_get(key: str) -> dict[str, Any] | None:
    entry = _SEARCH_CACHE.get(key)
    if not entry:
        return None
    expires_at, cached = entry
    if time.time() > expires_at:
        _SEARCH_CACHE.pop(key, None)
        return None
    return cached


def _search_cache_set(key: str, parsed: dict[str, Any]) -> None:
    _SEARCH_CACHE[key] = (time.time() + SEARCH_CACHE_TTL_MINUTES * 60, parsed)


def call_openai_live_search(query: str, previous_intent: dict[str, Any] | None) -> dict[str, Any]:
    """Single OpenAI Responses API call: understands intent AND performs web
    search. Retries once with backoff on a rate-limit error specifically,
    before letting the caller fall back to demo mode."""
    prompt = (
        f"Previous shopping intent (JSON, may be empty): {json.dumps(previous_intent or {}, ensure_ascii=False)}\n\n"
        f"New shopper message: {query}\n\n"
        "Search the web now and respond with the JSON object described in your instructions."
    )

    attempts = 0
    max_attempts = 3
    backoff_seconds = 1.0
    last_exc: Exception | None = None
    while attempts < max_attempts:
        attempts += 1
        try:
            response = OPENAI_CLIENT.responses.create(
                model=OPENAI_MODEL,
                instructions=LIVE_SYSTEM_PROMPT,
                tools=[{"type": "web_search"}],
                input=prompt,
            )
            break
        except Exception as exc:  # noqa: BLE001 - only retry the specific rate-limit case below
            is_rate_limit = RateLimitError is not None and isinstance(exc, RateLimitError)
            last_exc = exc
            if not is_rate_limit or attempts >= max_attempts:
                raise
            time.sleep(backoff_seconds)
            backoff_seconds *= 2
    else:  # pragma: no cover - loop always breaks or raises above
        raise last_exc or RuntimeError("OpenAI call failed with no exception captured")

    raw_text = (response.output_text or "").strip()
    raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.I | re.S)
    match = re.search(r"\{.*\}", raw_text, flags=re.S)
    if not match:
        raise ValueError("OpenAI response did not contain a JSON object")
    return json.loads(match.group(0))


def run_live_search(
    query: str, previous_intent: dict[str, Any] | None, search_id: str | None = None
) -> dict[str, Any]:
    """Returns a full /api/search-shaped response dict. Never raises to the caller;
    on any failure it returns a fallback_available=True demo response instead.

    If `search_id` is given (a refinement of an existing session), the same
    search_id is reused and its search_sessions/search_products rows are
    updated in place instead of minting a new session - so "similar products"
    and the URL a user bookmarks/shares keep working across a refinement."""
    if not OPENAI_CLIENT:
        return fallback_demo_search(
            query, previous_intent,
            error="Live search is temporarily unavailable (no OpenAI API key configured).",
            search_id=search_id,
        )

    cache_key = _search_cache_key(query, previous_intent)
    cached = _search_cache_get(cache_key)
    if cached is not None:
        parsed = cached
    else:
        try:
            parsed = call_openai_live_search(query, previous_intent)
        except Exception as exc:  # noqa: BLE001 - any AI/network failure must degrade gracefully
            return fallback_demo_search(
                query, previous_intent, error=f"Live search is temporarily unavailable: {exc}", search_id=search_id
            )
        _search_cache_set(cache_key, parsed)

    intent = parsed.get("intent") or {}
    intent = {**(previous_intent or {}), **intent, "product_type": "sneakers"}
    raw_products = parsed.get("products") or []
    products = [normalize_live_product(p) for p in raw_products]
    products = [p for p in products if p]

    for p in products:
        p["match_score"] = score_against_intent(p, intent)
    products.sort(key=lambda p: (-(p["match_score"] or 0),))

    if products:
        persist_live_products(products)
        attach_price_history_and_recommendation(products)

    search_id = search_id or str(uuid.uuid4())
    save_search_session(search_id, query, intent, [p["id"] for p in products], mode="live")

    for p in products:
        p["similar_product_ids"] = [other["id"] for other in products if other["id"] != p["id"]]

    return {
        "success": True,
        "search_id": search_id,
        "query": query,
        "message": safe_str(parsed.get("message")) or f"Found {len(products)} live results for you.",
        "intent": intent,
        "products": products,
        "count": len(products),
        "mode": "live",
        "fallback_available": True,
    }


def fallback_demo_search(
    query: str,
    previous_intent: dict[str, Any] | None,
    error: str | None,
    is_deliberate_demo: bool = False,
    search_id: str | None = None,
) -> dict[str, Any]:
    intent = local_parse_intent(query, previous_intent)
    products = match_demo_products(intent)
    search_id = search_id or str(uuid.uuid4())
    save_search_session(search_id, query, intent, [p["id"] for p in products], mode="demo")
    for p in products:
        p["similar_product_ids"] = [other["id"] for other in products if other["id"] != p["id"]]
        try:
            demo_id = int(str(p["id"]).replace("demo-", ""))
            p["price_history"] = demo_price_history(demo_id, p["price"])
            p["buy_recommendation"] = build_buy_recommendation(p["price"], [h["price"] for h in p["price_history"]])
        except ValueError:
            pass
    message = (
        "Here are demo catalog matches."
        if is_deliberate_demo
        else "Live search is temporarily unavailable, so here are demo catalog matches instead."
    )
    return {
        "success": is_deliberate_demo,
        "search_id": search_id,
        "query": query,
        "message": message,
        "intent": intent,
        "products": products,
        "count": len(products),
        "mode": "demo",
        "error": None if is_deliberate_demo else error,
        "fallback_available": True,
    }


def save_search_session(search_id: str, query: str, intent: dict[str, Any], product_keys: list[str], mode: str) -> None:
    """Creates a new search session, or - when search_id already exists (a
    refinement continuing a prior session) - updates it in place: the latest
    query/intent/mode win, and the product list is replaced with this
    refinement's results rather than appended to."""
    conn = db()
    conn.execute(
        """INSERT INTO search_sessions (id, query, intent_json, mode, created_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
               query = excluded.query,
               intent_json = excluded.intent_json,
               mode = excluded.mode""",
        (search_id, query, json.dumps(intent, ensure_ascii=False), mode, datetime.utcnow().isoformat()),
    )
    conn.execute("DELETE FROM search_products WHERE search_id = ?", (search_id,))
    conn.executemany(
        "INSERT OR REPLACE INTO search_products (search_id, product_key, rank) VALUES (?,?,?)",
        [(search_id, key, i) for i, key in enumerate(product_keys)],
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Price history + buy recommendation (shared by live and demo products)
# --------------------------------------------------------------------------

def build_buy_recommendation(current_price: float | None, observed_prices: list[float]) -> dict[str, Any]:
    observed_prices = [p for p in observed_prices if p is not None]
    if current_price is None or len(observed_prices) < 2:
        return {
            "status": "insufficient_data",
            "confidence": 0,
            "current_price": current_price,
            "lowest_observed_price": min(observed_prices) if observed_prices else None,
            "highest_observed_price": max(observed_prices) if observed_prices else None,
            "average_observed_price": round(sum(observed_prices) / len(observed_prices), 2) if observed_prices else None,
            "explanation": "We need more price observations before making a reliable timing recommendation.",
        }

    lowest = min(observed_prices)
    highest = max(observed_prices)
    average = sum(observed_prices) / len(observed_prices)
    confidence = min(95, 30 + len(observed_prices) * 10)

    if current_price <= lowest * 1.03:
        status = "buy_now"
        explanation = f"Current price ₹{current_price:,.0f} is close to the lowest price Bella Vista has observed (₹{lowest:,.0f})."
    elif current_price <= average:
        status = "good_price"
        explanation = f"Current price ₹{current_price:,.0f} is below the average observed price (₹{average:,.0f})."
    elif current_price > average * 1.1:
        status = "wait"
        explanation = f"Current price ₹{current_price:,.0f} is notably above the recent observed range. Historically this product has been cheaper than its current price."
    else:
        status = "good_price"
        explanation = f"Current price ₹{current_price:,.0f} is within the typical observed range for this product."

    return {
        "status": status,
        "confidence": round(confidence),
        "current_price": current_price,
        "lowest_observed_price": round(lowest, 2),
        "highest_observed_price": round(highest, 2),
        "average_observed_price": round(average, 2),
        "explanation": explanation,
    }


def get_live_price_history(product_key: str) -> list[dict[str, Any]]:
    conn = db()
    rows = conn.execute(
        "SELECT price, observed_at FROM price_history WHERE product_key = ? ORDER BY observed_at ASC",
        (product_key,),
    ).fetchall()
    conn.close()
    return [{"date": r["observed_at"][:10], "price": r["price"]} for r in rows]


def attach_price_history_and_recommendation(products: list[dict[str, Any]]) -> None:
    for p in products:
        history = get_live_price_history(p["id"])
        p["price_history"] = history
        p["buy_recommendation"] = build_buy_recommendation(p["price"], [h["price"] for h in history])


def live_product_by_key(product_key: str) -> dict[str, Any] | None:
    conn = db()
    row = conn.execute("SELECT * FROM live_products WHERE product_key = ?", (product_key,)).fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    return new_product_shell(
        id=item["product_key"],
        name=item["name"],
        brand=item["brand"],
        price=item["price"],
        currency=item["currency"],
        original_price=item["original_price"],
        discount_percent=item["discount_percent"],
        image_url=item["image_url"],
        product_url=item["product_url"],
        store=item["store"],
        rating=item["rating"],
        review_count=item["review_count"],
        description=item["description"],
        colors=item["colors"].split(",") if item["colors"] else [],
        category=item["category"],
        availability=item["availability"],
        source_url=item["source_url"],
        source_title=item["source_title"],
        source="live",
    )


# --------------------------------------------------------------------------
# API models
# --------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    previous_intent: dict[str, Any] = Field(default_factory=dict)


class RefineRequest(BaseModel):
    query: str
    search_id: str | None = None
    previous_intent: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": BELLA_VISTA_MODE,
        "live_available": OPENAI_CLIENT is not None,
        "model": OPENAI_MODEL if OPENAI_CLIENT else None,
    }


@app.post("/api/search")
def search(payload: SearchRequest) -> dict[str, Any]:
    query = payload.query.strip()
    if not query:
        raise HTTPException(400, "Search query is required")
    if BELLA_VISTA_MODE == "demo":
        return fallback_demo_search(query, payload.previous_intent, error=None, is_deliberate_demo=True)
    return run_live_search(query, payload.previous_intent)


@app.post("/api/search/refine")
def refine(payload: RefineRequest) -> dict[str, Any]:
    query = payload.query.strip()
    if not query:
        raise HTTPException(400, "Search query is required")

    # Only reuse search_id if that session actually exists; an unknown/stale
    # id (e.g. from an old bookmarked link) silently starts a fresh session
    # instead of erroring, since the request itself is still perfectly valid.
    search_id = payload.search_id
    if search_id:
        conn = db()
        exists = conn.execute("SELECT 1 FROM search_sessions WHERE id = ?", (search_id,)).fetchone()
        conn.close()
        if not exists:
            search_id = None

    if BELLA_VISTA_MODE == "demo":
        return fallback_demo_search(query, payload.previous_intent, error=None, is_deliberate_demo=True, search_id=search_id)
    return run_live_search(query, payload.previous_intent, search_id=search_id)


@app.get("/api/products/{product_id}")
def product_detail(product_id: str) -> dict[str, Any]:
    if product_id.startswith("demo-"):
        conn = db()
        row = conn.execute("SELECT * FROM demo_products WHERE id = ?", (product_id.replace("demo-", ""),)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(404, "Product not found")
        item = demo_row_to_product(row)
        item["match_score"] = 90
        item["match_reasons"] = ["Bella Vista favorite"]
        demo_id = int(row["id"])
        item["price_history"] = demo_price_history(demo_id, item["price"])
        item["buy_recommendation"] = build_buy_recommendation(item["price"], [h["price"] for h in item["price_history"]])
        return item

    item = live_product_by_key(product_id)
    if not item:
        raise HTTPException(404, "Product not found")
    history = get_live_price_history(product_id)
    item["price_history"] = history
    item["buy_recommendation"] = build_buy_recommendation(item["price"], [h["price"] for h in history])
    return item


@app.get("/api/products/{product_id}/price-history")
def price_history_endpoint(product_id: str) -> dict[str, Any]:
    product = product_detail(product_id)  # reuses lookup + not-found handling
    return {
        "current_price": product["price"],
        "history": product["price_history"],
        "buy_recommendation": product["buy_recommendation"],
    }


@app.get("/api/search/{search_id}/similar")
def search_similar(search_id: str, exclude: str | None = None) -> dict[str, Any]:
    conn = db()
    session = conn.execute("SELECT * FROM search_sessions WHERE id = ?", (search_id,)).fetchone()
    if not session:
        conn.close()
        raise HTTPException(404, "Search session not found")
    rows = conn.execute(
        "SELECT product_key FROM search_products WHERE search_id = ? ORDER BY rank ASC", (search_id,)
    ).fetchall()
    conn.close()
    product_keys = [r["product_key"] for r in rows if r["product_key"] != exclude]
    products = []
    for key in product_keys:
        item = None
        if key.startswith("demo-"):
            item = product_detail(key)
        else:
            item = live_product_by_key(key)
        if item:
            products.append(item)
    return {"search_id": search_id, "products": products, "count": len(products)}


# --------------------------------------------------------------------------
# Legacy/demo browse endpoints (kept for the collection & deals pages)
# --------------------------------------------------------------------------

@app.get("/api/products")
def products(limit: int = 72, brand: str | None = None, style: str | None = None) -> list[dict[str, Any]]:
    conn = db()
    query, args = "SELECT * FROM demo_products WHERE 1=1", []
    if brand:
        query += " AND brand = ?"
        args.append(brand)
    if style:
        query += " AND style = ?"
        args.append(style)
    rows = conn.execute(query + " LIMIT ?", [*args, limit]).fetchall()
    conn.close()
    return [demo_row_to_product(r) for r in rows]


@app.get("/api/deals")
def deals() -> list[dict[str, Any]]:
    return [p for p in products(72) if (p["discount_percent"] or 0) >= 20][:18]
