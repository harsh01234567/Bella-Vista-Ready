import axios from "axios";
import type { HealthResponse, Product, SearchIntent, SearchResponse, SearchSession } from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api";

const SESSION_KEY = "bv_last_search";

export async function getHealth(): Promise<HealthResponse> {
  const r = await axios.get<HealthResponse>(API_BASE + "/health");
  return r.data;
}

export async function runSearch(query: string, previousIntent: SearchIntent = {}): Promise<SearchResponse> {
  const r = await axios.post<SearchResponse>(API_BASE + "/search", { query, previous_intent: previousIntent });
  return r.data;
}

// Continues an existing search session (a follow-up chat message refining a
// prior search) rather than starting a brand-new one. Passing the current
// searchId lets the backend update that session in place, so a bookmarked
// /product/:id?search_id=... link and "similar products" keep working
// against the latest refinement instead of the original search.
export async function runRefine(
  query: string,
  previousIntent: SearchIntent = {},
  searchId?: string
): Promise<SearchResponse> {
  const r = await axios.post<SearchResponse>(API_BASE + "/search/refine", {
    query,
    previous_intent: previousIntent,
    search_id: searchId,
  });
  return r.data;
}

export async function getProduct(id: string): Promise<Product> {
  const r = await axios.get<Product>(API_BASE + "/products/" + encodeURIComponent(id));
  return r.data;
}

export async function getSimilarFromSearch(searchId: string, excludeId: string): Promise<Product[]> {
  const r = await axios.get<{ products: Product[] }>(
    API_BASE + "/search/" + encodeURIComponent(searchId) + "/similar",
    { params: { exclude: excludeId } }
  );
  return r.data.products;
}

// --- session persistence ---------------------------------------------------
// Keeps the full result set of the user's most recent search around so the
// product detail page can show "similar products" from the SAME search
// without re-querying the AI for every card click.

export function saveSearchSession(res: SearchResponse): void {
  const session: SearchSession = {
    search_id: res.search_id,
    query: res.query,
    intent: res.intent,
    products: res.products,
    mode: res.mode,
    created_at: new Date().toISOString(),
  };
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    // sessionStorage can fail in private/incognito contexts - not critical
  }
}

export function loadSearchSession(): SearchSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as SearchSession) : null;
  } catch {
    return null;
  }
}

export function findInLastSession(productId: string): { product: Product; session: SearchSession } | null {
  const session = loadSearchSession();
  if (!session) return null;
  const product = session.products.find((p) => p.id === productId);
  return product ? { product, session } : null;
}
