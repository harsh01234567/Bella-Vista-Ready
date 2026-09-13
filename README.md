# Bella Vista

Bella Vista is a conversational **live** sneaker shopping platform. Describe
what you want and Bella Vista searches the real web (via the OpenAI Responses
API + hosted `web_search` tool) for current listings, then shows real prices,
real images, and a price-history-driven "should I buy now?" recommendation —
all pulled from data Bella Vista has actually observed.

A local demo mode (72 deterministic seeded products) remains available so the
project can always be shown even without an API key.

## How it works

```
User types a request
        │
        ▼
React frontend (chat-style /discover page)
        │  POST /api/search
        ▼
FastAPI backend
        │  OpenAI Responses API + web_search tool
        ▼
Real web listings are found and normalized into Bella Vista's Product schema
        │
        ▼
Frontend shows real product cards (image, price, store, match score)
        │  user clicks a card
        ▼
/product/:id — price history (real observations), Buy/Wait recommendation,
"Similar Products" (the OTHER results from the same search)
```

## Run locally

### Backend
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy ..\.env.example .env   # then fill in OPENAI_API_KEY
uvicorn main:app --reload --port 8000
```

### Frontend
```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The API is available at http://localhost:8000/docs.

## Environment variables

Copy `.env.example` to `backend/.env` (never commit the real file — it's
already git-ignored):

| Variable | Purpose |
| --- | --- |
| `BELLA_VISTA_MODE` | `live` (default) uses OpenAI + web search for real results. `demo` always uses the offline seeded catalog. |
| `OPENAI_API_KEY` | Backend-only secret. **Never** exposed to the frontend/browser/bundle. |
| `OPENAI_MODEL` | Any current OpenAI model that supports the Responses API + `web_search` tool (default `gpt-4.1-mini` — **not verified against current OpenAI docs, see Known limitations below**). |
| `BELLA_VISTA_ALLOWED_ORIGINS` | Comma-separated frontend origins allowed by CORS in production. Unset = Vite dev server origins only (not `*`). Set to `*` explicitly if you really want any origin. |
| `BELLA_VISTA_SEARCH_CACHE_TTL_MINUTES` | Minutes an identical live search (same query + intent) is served from an in-memory cache before OpenAI is called again. Default `15`. |
| `BELLA_VISTA_SESSION_RETENTION_DAYS` | Days to keep `search_sessions`/`search_products` rows before startup cleanup prunes them. Default `30`. |
| `BELLA_VISTA_PRICE_HISTORY_RETENTION_DAYS` | Days to keep `price_history` rows before startup cleanup prunes them. Default `180`. |
| `BELLA_VISTA_VALIDATE_IMAGE_URLS` | If `true`, HEAD-checks each product `image_url` and nulls it out unless it resolves with an `image/*` content-type. Default `false` — off because it adds a network round trip per product per search. |

If `BELLA_VISTA_MODE=live` but no API key is configured, or a live search call
fails (timeout, rate limit, malformed response, etc.), the backend
automatically and transparently falls back to demo-catalog results rather than
crashing — the response includes `"fallback_available": true` and an `error`
message the frontend surfaces as a small banner. Rate-limit errors
specifically (`openai.RateLimitError`) get one retry with exponential backoff
before falling back.

## Live mode vs. demo mode

- **Live mode** — every search is a single OpenAI Responses API call that both
  understands the request (merging it with the previous conversational
  intent) *and* performs a web search, so Bella Vista never issues more than
  one AI call per user search. Every field in a live product (price, image,
  rating, availability, etc.) is either something the model actually found via
  search, or `null`. Nothing is fabricated.
- **Demo mode** — the original 72-item deterministic local catalog, useful for
  offline demos. Demo products are clearly labeled (`source: "demo"`) in the
  API and UI so they're never confused with verified live data.

## Price history methodology

Bella Vista does **not** ask the AI to invent historical prices — that isn't
possible from a single web search. Instead, every time a live product
resurfaces in a search result, its current price is recorded as one
observation in the `price_history` SQLite table (deduplicated within a short
time window so repeated searches don't spam the table). A product's price
chart and stats (lowest/highest/average observed, trend) are built purely
from these real, stored observations. If a product has fewer than two
observations, the UI says **"Not enough price history yet"** instead of
drawing a fabricated graph.

## Buy recommendation methodology

`buy_recommendation` is computed from the same real observed prices — never a
prediction of future prices:

- 🟢 **Buy Now** — current price is at or near the lowest observed price.
- 🟡 **Good Price** — current price is at or below the average observed price.
- 🔴 **Wait** — current price is well above the recent observed range.
- ⚪ **Insufficient Data** — fewer than two observations exist yet.

Bella Vista uses language like *"historically cheaper than its current
price"* rather than ever claiming a future price drop.

## Database

SQLite (`backend/bella_vista.db`, git-ignored). Tables:

- `demo_products` — the offline seeded catalog.
- `live_products` — a cache of the most recently seen details for each
  real-world product Bella Vista has found (keyed by a stable hash of its
  product URL/name/store).
- `price_history` — every real price observation Bella Vista has recorded.
- `search_sessions` / `search_products` — each search's query, resolved
  intent, and the ordered list of products it returned, so a product detail
  page can reconstruct "similar products" from the *same* search without
  re-querying the AI.

## API

- `GET /api/health` — current mode + whether live search is actually available.
- `POST /api/search` — `{query, previous_intent}` → live (or demo) results + `search_id`.
- `POST /api/search/refine` — `{query, previous_intent, search_id}`. When `search_id` matches an existing session, that session's query/intent/products are updated **in place** (same `search_id` returned) instead of minting a new session, so a shared/bookmarked `/product/:id?search_id=...` link and "similar products" stay consistent across a refinement. An unknown/stale `search_id` silently starts a fresh session instead of erroring. The Discover chat page calls this (not `/api/search`) for every message after the first.
- `GET /api/products/{id}` — a single product (live or demo) with price history + buy recommendation attached.
- `GET /api/products/{id}/price-history` — just the price-history + recommendation.
- `GET /api/search/{search_id}/similar?exclude={id}` — the other products from that search.
- `GET /api/products`, `GET /api/deals` — legacy demo-catalog browse endpoints used by the Collection/Deals pages.

## Product imagery

Live-mode images come directly from the product listing Bella Vista found; if
no reliable image URL is available, `image_url` is `null` and the frontend
shows a clean Bella Vista placeholder instead of breaking. Demo-mode photos
live under `frontend/public/images/` (downloaded from Unsplash under the
Unsplash License) and are reused across visually-similar demo items.

## Security

`OPENAI_API_KEY` is read only by the FastAPI backend from `backend/.env` and
is never sent to the frontend, embedded in the JS bundle, or logged. The
`.gitignore` excludes `backend/.env` and `backend/*.db`. CORS is restricted to
`BELLA_VISTA_ALLOWED_ORIGINS` (see above) rather than `*`.

## Tests

```powershell
# backend
cd backend
pip install -r requirements-dev.txt
pytest -v

# frontend
cd frontend
npm install
npm test
```

Backend tests cover `normalize_live_product`, `build_buy_recommendation`,
`score_against_intent`, the dedup logic in `record_price_observation`, and the
session-upsert behavior of `save_search_session` used by `/api/search/refine`.
Frontend tests cover `ProductImage`'s fallback rendering and the
`sessionStorage`-backed search-session helpers in `api.ts`.

## Known limitations / what's unverified

Some things in this codebase have been implemented but not exercised end to
end, because the environment they were written in has no network access
(can't reach `api.openai.com`, PyPI, or npm) and no browser to render in:

- **Live OpenAI calls are still unverified.** `run_live_search` /
  `call_openai_live_search` have never actually been run against a real
  `OPENAI_API_KEY` — only the "no key configured" fallback path has been
  exercised (via code review, not execution). Before trusting this in
  production: confirm `gpt-4.1-mini` (or whatever you set `OPENAI_MODEL` to)
  actually supports the Responses API `web_search` tool today, confirm
  `output_text` reliably parses as the JSON shape `LIVE_SYSTEM_PROMPT` asks
  for, and check whether real search results actually carry usable
  `image_url`/`product_url` values — tune the prompt based on what you see.
- **Nothing in this repo has been executed in this session** — not
  `pip install`, not `pytest`, not `npm install`/`tsc -b`/`vite build`, not a
  curl smoke test. All of the changes described above are believed correct
  from careful reading, but you should run the full check sequence (backend
  import + pytest, `tsc -b` + `vite build`, a demo-mode curl smoke test
  through search → product detail → similar products, and a live-mode test
  with a real key) before deploying.
- **Mobile/responsive layout has never been rendered in a browser.** The CSS
  for the price-history/buy-recommendation/notice sections includes
  `@media(max-width:800px)` rules, but nobody has looked at them on an actual
  ~375px viewport. Run the dev server and check the Discover and
  ProductDetail pages at mobile width.
- **The in-memory search cache and startup cleanup are single-process only.**
  They won't coordinate across multiple backend workers/instances. Fine at
  this app's current scale; revisit (shared cache, a real scheduled job
  instead of startup-only cleanup) before scaling out.
# Bella-Vista-Ready
