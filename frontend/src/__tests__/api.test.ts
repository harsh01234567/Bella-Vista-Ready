// NOTE (handoff): written but never run - see ProductImage.test.tsx for why.
import { beforeEach, describe, expect, it } from "vitest";
import { findInLastSession, loadSearchSession, saveSearchSession } from "../api";
import type { Product, SearchResponse } from "../types";

function product(id: string): Product {
  return {
    id,
    name: `Product ${id}`,
    brand: "Nike",
    price: 5000,
    currency: "INR",
    original_price: null,
    discount_percent: null,
    image_url: null,
    product_url: null,
    store: null,
    rating: null,
    review_count: null,
    description: null,
    colors: [],
    category: "Sneakers",
    match_score: null,
    match_reasons: [],
    source_url: null,
    source_title: null,
    availability: null,
    price_history: [],
    buy_recommendation: null,
    similar_product_ids: [],
    source: "live",
  };
}

function searchResponse(): SearchResponse {
  return {
    success: true,
    search_id: "search-123",
    query: "white nike sneakers",
    message: "Found 2 results",
    intent: { colors: ["white"] },
    products: [product("p1"), product("p2")],
    count: 2,
    mode: "live",
  };
}

describe("search session persistence", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("returns null when nothing has been saved yet", () => {
    expect(loadSearchSession()).toBeNull();
  });

  it("round-trips a saved session through sessionStorage", () => {
    saveSearchSession(searchResponse());
    const session = loadSearchSession();
    expect(session).not.toBeNull();
    expect(session!.search_id).toBe("search-123");
    expect(session!.products).toHaveLength(2);
  });

  it("findInLastSession locates a product from the last saved session", () => {
    saveSearchSession(searchResponse());
    const found = findInLastSession("p2");
    expect(found).not.toBeNull();
    expect(found!.product.id).toBe("p2");
    expect(found!.session.search_id).toBe("search-123");
  });

  it("findInLastSession returns null for a product not in the last session", () => {
    saveSearchSession(searchResponse());
    expect(findInLastSession("not-a-real-id")).toBeNull();
  });

  it("findInLastSession returns null when no session was ever saved", () => {
    expect(findInLastSession("p1")).toBeNull();
  });
});
