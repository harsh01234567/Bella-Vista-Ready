// Unified types for Bella Vista's live + demo product pipeline.
// Every backend endpoint returns Products in this exact shape, whether they
// came from a live OpenAI web search or the offline demo catalog.

export interface PriceHistoryPoint {
  date: string;
  price: number;
}

export type BuyRecommendationStatus = "buy_now" | "good_price" | "wait" | "insufficient_data";

export interface BuyRecommendation {
  status: BuyRecommendationStatus;
  confidence: number;
  current_price: number | null;
  lowest_observed_price: number | null;
  highest_observed_price: number | null;
  average_observed_price: number | null;
  explanation: string;
}

export interface Product {
  id: string;
  name: string | null;
  brand: string | null;
  price: number | null;
  currency: string;
  original_price: number | null;
  discount_percent: number | null;
  image_url: string | null;
  product_url: string | null;
  store: string | null;
  rating: number | null;
  review_count: number | null;
  description: string | null;
  colors: string[];
  category: string;
  match_score: number | null;
  match_reasons: string[];
  source_url: string | null;
  source_title: string | null;
  availability: string | null;
  price_history: PriceHistoryPoint[];
  buy_recommendation: BuyRecommendation | null;
  similar_product_ids: string[];
  source: "live" | "demo";
}

export interface SearchIntent {
  product_type?: string;
  colors?: string[];
  max_price?: number | null;
  min_price?: number | null;
  brand?: string | null;
  style?: string[] | string | null;
  use_case?: string[];
  keywords?: string[];
  cheaper?: boolean;
  [key: string]: unknown;
}

export interface SearchResponse {
  success: boolean;
  search_id: string;
  query: string;
  message: string;
  intent: SearchIntent;
  products: Product[];
  count: number;
  mode: "live" | "demo";
  error?: string | null;
  fallback_available?: boolean;
}

export interface SearchSession {
  search_id: string;
  query: string;
  intent: SearchIntent;
  products: Product[];
  mode: "live" | "demo";
  created_at: string;
}

export interface HealthResponse {
  status: string;
  mode: "live" | "demo";
  live_available: boolean;
  model: string | null;
}

export interface PriceHistoryResponse {
  current_price: number | null;
  history: PriceHistoryPoint[];
  buy_recommendation: BuyRecommendation | null;
}
