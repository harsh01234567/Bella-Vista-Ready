// NOTE (handoff): written but never run - this sandbox had no network access
// to `npm install` vitest/jsdom/testing-library, so this has not been
// executed. Run `npm install && npm test` locally before trusting it.
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ProductImage } from "../main";
import type { Product } from "../types";

function baseProduct(overrides: Partial<Product> = {}): Product {
  return {
    id: "p1",
    name: "Cloud Runner",
    brand: "Nike",
    price: 5000,
    currency: "INR",
    original_price: null,
    discount_percent: null,
    image_url: null,
    product_url: null,
    store: "Nike.com",
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
    ...overrides,
  } as Product;
}

describe("ProductImage", () => {
  it("renders the fallback UI when image_url is null", () => {
    render(<ProductImage p={baseProduct({ image_url: null })} />);
    expect(screen.queryByRole("img", { hidden: false })).not.toBeInTheDocument();
    expect(screen.getByText("Cloud Runner")).toBeInTheDocument();
    // live-sourced products get an explicit "not verified" label, per the
    // data-integrity rule that live image_urls are shown but not vouched for
    expect(screen.getByText("IMAGE NOT VERIFIED")).toBeInTheDocument();
  });

  it("renders an <img> when image_url is present", () => {
    render(<ProductImage p={baseProduct({ image_url: "https://example.com/shoe.jpg" })} />);
    const img = screen.getByRole("img") as HTMLImageElement;
    expect(img).toBeInTheDocument();
    expect(img.src).toBe("https://example.com/shoe.jpg");
  });

  it("falls back to the placeholder after the <img> fires onError", () => {
    render(<ProductImage p={baseProduct({ image_url: "https://example.com/broken.jpg" })} />);
    const img = screen.getByRole("img");
    fireEvent.error(img);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Cloud Runner")).toBeInTheDocument();
  });

  it("shows 'SNEAKER' (not 'IMAGE NOT VERIFIED') for demo-sourced products with no image", () => {
    render(<ProductImage p={baseProduct({ image_url: null, source: "demo" })} />);
    expect(screen.getByText("SNEAKER")).toBeInTheDocument();
  });
});
