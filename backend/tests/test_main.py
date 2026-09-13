"""
Unit tests for the pure-ish helper functions in backend/main.py.

See conftest.py's module docstring: written but not yet run against real
installed dependencies (sandbox had no network to `pip install`). Run with:

    cd backend
    pip install -r requirements.txt
    pip install pytest
    pytest -v
"""

from __future__ import annotations

from datetime import datetime, timedelta

import main


# --------------------------------------------------------------------------
# normalize_live_product
# --------------------------------------------------------------------------

def test_normalize_live_product_no_name_returns_none():
    assert main.normalize_live_product({}) is None
    assert main.normalize_live_product({"name": "   "}) is None
    assert main.normalize_live_product("not a dict") is None


def test_normalize_live_product_missing_fields_become_null():
    raw = {"name": "Air Runner 2000"}
    product = main.normalize_live_product(raw)
    assert product is not None
    assert product["name"] == "Air Runner 2000"
    assert product["price"] is None
    assert product["image_url"] is None
    assert product["product_url"] is None
    assert product["rating"] is None
    assert product["review_count"] is None
    assert product["colors"] == []
    # currency defaults even when unspecified, everything else stays null/empty
    assert product["currency"] == "INR"


def test_normalize_live_product_invalid_urls_become_null():
    raw = {
        "name": "Street Glide",
        "image_url": "not-a-url",
        "product_url": "javascript:alert(1)",
    }
    product = main.normalize_live_product(raw)
    assert product["image_url"] is None
    assert product["product_url"] is None


def test_normalize_live_product_valid_data_passes_through():
    raw = {
        "name": "Cloud Runner",
        "brand": "Nike",
        "price": 5499,
        "original_price": 6999,
        "currency": "INR",
        "image_url": "https://example.com/shoe.jpg",
        "product_url": "https://example.com/product/123",
        "store": "Nike.com",
        "rating": 4.5,
        "review_count": 128,
        "colors": ["white", "black"],
        "availability": "in_stock",
    }
    product = main.normalize_live_product(raw)
    assert product["name"] == "Cloud Runner"
    assert product["brand"] == "Nike"
    assert product["price"] == 5499
    assert product["original_price"] == 6999
    assert product["image_url"] == "https://example.com/shoe.jpg"
    assert product["product_url"] == "https://example.com/product/123"
    assert product["colors"] == ["white", "black"]
    # discount computed from price/original_price, not fabricated
    assert product["discount_percent"] == round((1 - 5499 / 6999) * 100)
    # id is a stable hash of product_url|name|store
    assert product["id"] == main.make_product_key("https://example.com/product/123", "Cloud Runner", "Nike.com")


def test_normalize_live_product_never_fabricates_discount_without_original_price():
    raw = {"name": "No Discount Info", "price": 4000}
    product = main.normalize_live_product(raw)
    assert product["discount_percent"] is None


# --------------------------------------------------------------------------
# build_buy_recommendation
# --------------------------------------------------------------------------

def test_build_buy_recommendation_insufficient_data_no_history():
    rec = main.build_buy_recommendation(5000, [])
    assert rec["status"] == "insufficient_data"
    assert rec["confidence"] == 0


def test_build_buy_recommendation_insufficient_data_single_observation():
    rec = main.build_buy_recommendation(5000, [5200])
    assert rec["status"] == "insufficient_data"


def test_build_buy_recommendation_insufficient_data_no_current_price():
    rec = main.build_buy_recommendation(None, [5000, 5200, 4900])
    assert rec["status"] == "insufficient_data"
    assert rec["current_price"] is None


def test_build_buy_recommendation_buy_now_near_lowest():
    # current price is within 3% of the lowest ever observed
    rec = main.build_buy_recommendation(4900, [4900, 5200, 5500, 6000])
    assert rec["status"] == "buy_now"
    assert rec["lowest_observed_price"] == 4900
    assert rec["highest_observed_price"] == 6000


def test_build_buy_recommendation_good_price_below_average_but_not_near_lowest():
    # lowest=5000 (current is not within 3% of it), average=6000, current(5500) <= average
    rec = main.build_buy_recommendation(5500, [5000, 6000, 7000])
    assert rec["status"] == "good_price"


def test_build_buy_recommendation_wait_when_notably_above_average():
    rec = main.build_buy_recommendation(9000, [5000, 5200, 5100])
    assert rec["status"] == "wait"


def test_build_buy_recommendation_confidence_scales_with_observation_count():
    rec_few = main.build_buy_recommendation(5000, [5000, 5100])
    rec_many = main.build_buy_recommendation(5000, [5000, 5100, 4900, 5200, 5300, 4950, 5050])
    assert rec_many["confidence"] >= rec_few["confidence"]
    assert rec_many["confidence"] <= 95


# --------------------------------------------------------------------------
# score_against_intent
# --------------------------------------------------------------------------

def test_score_against_intent_color_match_increases_score():
    product = {"colors": ["white", "black"], "price": 5000, "brand": "Nike", "description": ""}
    base = main.score_against_intent({**product, "colors": []}, {"colors": ["white"]})
    matched = main.score_against_intent(product, {"colors": ["white"]})
    assert matched > base


def test_score_against_intent_over_budget_lowers_score():
    product = {"colors": [], "price": 9000, "brand": None, "description": ""}
    within_budget = main.score_against_intent({**product, "price": 4000}, {"max_price": 6000})
    over_budget = main.score_against_intent(product, {"max_price": 6000})
    assert within_budget > over_budget


def test_score_against_intent_brand_mismatch_penalized():
    product_match = {"colors": [], "price": None, "brand": "Nike", "description": ""}
    product_mismatch = {"colors": [], "price": None, "brand": "Puma", "description": ""}
    intent = {"brand": "Nike"}
    assert main.score_against_intent(product_match, intent) > main.score_against_intent(product_mismatch, intent)


def test_score_against_intent_stays_within_bounds():
    product = {"colors": ["white"], "price": 100000, "brand": "Other", "description": ""}
    score = main.score_against_intent(product, {"colors": ["white"], "max_price": 100, "brand": "Nike"})
    assert 5 <= score <= 99


# --------------------------------------------------------------------------
# record_price_observation dedup logic
# --------------------------------------------------------------------------

def test_record_price_observation_dedups_within_window(temp_db):
    conn = main.db()
    main.record_price_observation(conn, "product-abc", 5000, "INR", "Nike.com")
    main.record_price_observation(conn, "product-abc", 5100, "INR", "Nike.com")  # same window -> skipped
    conn.commit()
    rows = conn.execute("SELECT * FROM price_history WHERE product_key = ?", ("product-abc",)).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["price"] == 5000  # the second call was a no-op


def test_record_price_observation_writes_new_row_outside_window(temp_db):
    conn = main.db()
    stale_time = (datetime.utcnow() - timedelta(hours=main.PRICE_OBSERVATION_WINDOW_HOURS + 1)).isoformat()
    conn.execute(
        "INSERT INTO price_history (product_key, price, currency, store, observed_at) VALUES (?,?,?,?,?)",
        ("product-xyz", 4800, "INR", "Nike.com", stale_time),
    )
    conn.commit()
    main.record_price_observation(conn, "product-xyz", 5200, "INR", "Nike.com")
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM price_history WHERE product_key = ? ORDER BY observed_at ASC", ("product-xyz",)
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[-1]["price"] == 5200


# --------------------------------------------------------------------------
# search session upsert (refine continuing a session in place) - item #7 fix
# --------------------------------------------------------------------------

def test_save_search_session_refine_reuses_id_and_replaces_products(temp_db):
    main.save_search_session("search-1", "white sneakers", {"colors": ["white"]}, ["p1", "p2"], mode="live")
    main.save_search_session("search-1", "white sneakers cheaper", {"colors": ["white"], "cheaper": True}, ["p3"], mode="live")

    conn = main.db()
    sessions = conn.execute("SELECT * FROM search_sessions WHERE id = ?", ("search-1",)).fetchall()
    products = conn.execute("SELECT * FROM search_products WHERE search_id = ?", ("search-1",)).fetchall()
    conn.close()

    assert len(sessions) == 1  # updated in place, not duplicated
    assert sessions[0]["query"] == "white sneakers cheaper"
    assert [p["product_key"] for p in products] == ["p3"]  # old product list replaced, not appended to
