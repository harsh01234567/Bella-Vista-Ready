import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import axios from "axios";
import {
  ArrowRight, Bot, ChevronRight, ExternalLink, Heart, Menu, Search, Sparkles, Star,
  TrendingDown, TrendingUp, Minus, X,
} from "lucide-react";
import { LineChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import "./styles.css";
import type { Product, SearchIntent } from "./types";
import { API_BASE, findInLastSession, getHealth, getProduct, getSimilarFromSearch, runRefine, runSearch, saveSearchSession } from "./api";

const examples = [
  "Red and white sneakers with gold accents under 5,000",
  "Black chunky sneakers with white soles under 4,000",
  "Comfortable blue sneakers for college around 5,000",
  "Sporty Adidas sneakers under 7,000",
  "Something like Air Force 1 but cheaper",
];

function formatINR(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return "₹" + n.toLocaleString("en-IN");
}

// ---------------------------------------------------------------------------
// Image with graceful fallback - never breaks the page if a real product
// image can't load (or was never found), per Bella Vista's data-integrity
// rules (we never fabricate an image).
// ---------------------------------------------------------------------------
export function ProductImage({ p, detail = false }: { p: Product; detail?: boolean }) {
  const [failed, setFailed] = useState(false);
  const showFallback = !p.image_url || failed;
  return (
    <>
      {!showFallback && (
        <img src={p.image_url!} alt={p.name ?? "Sneaker"} onError={() => setFailed(true)} loading="lazy" />
      )}
      {showFallback && (
        <div className={detail ? "image-fallback detail-fallback" : "image-fallback"} role="img" aria-label={p.name ?? "Sneaker"}>
          <span>{p.brand ?? "BELLA VISTA"}</span>
          <b>{p.name ?? "Image unavailable"}</b>
          <small>{p.source === "live" ? "IMAGE NOT VERIFIED" : "SNEAKER"}</small>
        </div>
      )}
    </>
  );
}

function Header() {
  const [open, setOpen] = useState(false);
  return (
    <header>
      <Link className="logo" to="/"><span>BV</span> BELLA VISTA</Link>
      <nav className={open ? "show" : ""}>
        <NavLink to="/discover">Discover</NavLink>
        <NavLink to="/deals">Deals</NavLink>
        <NavLink to="/about">About</NavLink>
      </nav>
      <button className="icon-btn menu" onClick={() => setOpen(!open)} aria-label="Menu">{open ? <X /> : <Menu />}</button>
    </header>
  );
}

function ProductCard({ p, featured = false, searchId }: { p: Product; featured?: boolean; searchId?: string }) {
  const to = "/product/" + encodeURIComponent(p.id) + (searchId ? "?search_id=" + encodeURIComponent(searchId) : "");
  return (
    <Link className={"product-card " + (featured ? "featured" : "")} to={to}>
      <div className="product-img">
        <ProductImage p={p} />
        {!!p.discount_percent && p.discount_percent > 0 && <b className="discount">-{p.discount_percent}%</b>}
        <button className="heart" onClick={(e) => e.preventDefault()} aria-label={`Save ${p.name}`}><Heart size={18} /></button>
      </div>
      <div className="product-info">
        <small>{p.brand ?? "Unknown brand"} · {p.store ?? "Bella Vista"}</small>
        <h3>{p.name}</h3>
        <div className="price">
          {formatINR(p.price)}
          {!!p.original_price && p.original_price !== p.price && <del>{formatINR(p.original_price)}</del>}
          {p.rating != null && <span><Star size={13} fill="currentColor" /> {p.rating}</span>}
        </div>
        {p.match_score != null && (
          <div className="match"><strong>{p.match_score}%</strong> match <em>{p.match_reasons?.[0]}</em></div>
        )}
        {p.availability === "out_of_stock" && <div className="availability-flag">Out of stock</div>}
      </div>
    </Link>
  );
}

function SearchHero() {
  const [query, setQuery] = useState("");
  const nav = useNavigate();
  const go = (q = query) => { if (q.trim()) nav("/discover?query=" + encodeURIComponent(q)); };
  return (
    <section className="hero">
      <div className="eyebrow"><Sparkles size={16} /> AI-POWERED SNEAKER DISCOVERY</div>
      <h1>Describe it.<br /><i>Bella Vista</i> finds it.</h1>
      <p>Tell us what your perfect sneakers look like. We'll search the live web and find real listings that match your style and budget.</p>
      <div className="search-box">
        <Search size={21} />
        <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && go()} placeholder="Describe your perfect sneakers..." aria-label="Describe your perfect sneakers" />
        <button onClick={() => go()}>Find my pair <ArrowRight size={17} /></button>
      </div>
      <div className="examples">
        <span>Try saying</span>
        {examples.slice(0, 3).map((x) => <button key={x} onClick={() => go(x)}>{x}</button>)}
      </div>
    </section>
  );
}

function Home() {
  return (
    <>
      <Header />
      <main>
        <SearchHero />
        <section className="home-intro">
          <div><small className="eyebrow">A BETTER WAY TO SHOP</small><h2>Less scrolling.<br /><i>More finding.</i></h2></div>
          <p>Bella Vista turns the way you talk into a smarter way to discover, searching real listings across the web instead of a fixed catalog. No endless filters. Just a conversation that gets you closer to the pair that feels right.</p>
        </section>
      </main>
    </>
  );
}

function Discover() {
  const [products, setProducts] = useState<Product[]>([]);
  const [searchId, setSearchId] = useState<string | undefined>(undefined);
  const [query, setQuery] = useState(new URLSearchParams(location.search).get("query") || "");
  const [intent, setIntent] = useState<SearchIntent>({});
  const [messages, setMessages] = useState<{ from: string; text: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const send = async (q = query) => {
    if (!q.trim()) return;
    setLoading(true);
    setSearched(true);
    setMessages((m) => [...m, { from: "you", text: q }]);
    try {
      // The very first message in a chat starts a new session; every
      // follow-up message refines that same session so search_id, and the
      // "similar products" it powers, stay consistent across the chat.
      const res = searchId ? await runRefine(q, intent, searchId) : await runSearch(q, intent);
      setIntent(res.intent);
      setProducts(res.products);
      setSearchId(res.search_id);
      saveSearchSession(res);
      setMessages((m) => [...m, { from: "ai", text: res.message }]);
      setNotice(res.mode === "demo" && res.error ? res.error : null);
    } catch (err) {
      setMessages((m) => [...m, { from: "ai", text: "Live search is temporarily unavailable. Please try again in a moment." }]);
      setNotice("Live search is temporarily unavailable.");
    }
    setQuery("");
    setLoading(false);
  };

  const initialQuerySent = useRef(false);
  useEffect(() => {
    if (query && !initialQuerySent.current) {
      initialQuerySent.current = true;
      send(query);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <Header />
      <main className="discover">
        <div className="chat-panel">
          <div className="chat-head">
            <div className="bot"><Bot size={20} /></div>
            <div><b>Bella Vista AI</b><small>Live web search for real sneaker listings</small></div>
            <span className="online">● Online</span>
          </div>
          <div className="messages">
            {!messages.length && (
              <div className="welcome"><Sparkles /><h2>What are you looking for?</h2><p>Describe a vibe, a color, a budget — or just name a pair you love.</p></div>
            )}
            {messages.map((m, i) => <div key={i} className={"bubble " + m.from}>{m.text}</div>)}
            {loading && <div className="bubble ai">Searching live products…</div>}
          </div>
          {notice && <div className="search-notice">{notice}</div>}
          <div className="chat-examples">
            {examples.slice(0, 2).map((x) => <button onClick={() => send(x)} key={x}>{x}</button>)}
          </div>
          <div className="composer">
            <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Refine your search..." />
            <button onClick={() => send()} aria-label="Send"><ArrowRight /></button>
          </div>
        </div>
        <div className="recommendations">
          <div className="section-heading">
            <div><small className="eyebrow">CURATED FOR YOU</small><h2>Your perfect matches</h2></div>
            <span>{products.length} results</span>
          </div>
          {loading && !products.length && <div className="empty"><Search /><p>Searching live products…</p></div>}
          {!loading && products.length > 0 && (
            <div className="product-grid">{products.map((p, i) => <ProductCard p={p} featured={i === 0} key={p.id} searchId={searchId} />)}</div>
          )}
          {!loading && searched && products.length === 0 && (
            <div className="empty"><Search /><p>No products found for this request. Try something like "white Nike sneakers under ₹6000".</p></div>
          )}
          {!loading && !searched && <div className="empty"><Search /><p>Your recommendations will appear here.</p></div>}
        </div>
      </main>
    </>
  );
}

function Listing({ deal = false }: { deal?: boolean }) {
  const [products, setProducts] = useState<Product[]>([]);
  useEffect(() => { axios.get(API_BASE + (deal ? "/deals" : "/products")).then((r) => setProducts(r.data)); }, [deal]);
  return (
    <>
      <Header />
      <main className="listing">
        <div className="page-title">
          <small className="eyebrow">{deal ? "LIMITED-TIME EDITS" : "THE COLLECTION"}</small>
          <h1>{deal ? "Good pairs. Better prices." : "Discover your next pair."}</h1>
          <p>{deal ? "Handpicked styles with room left in your budget." : "Explore a considered edit of sneakers, curated for every version of you."}</p>
        </div>
        <div className="product-grid">{products.map((p) => <ProductCard p={p} key={p.id} />)}</div>
      </main>
    </>
  );
}

function trendLabel(history: Product["price_history"]): { label: string; icon: React.ReactNode } {
  if (history.length < 2) return { label: "Not enough data", icon: <Minus size={16} /> };
  const first = history[0].price;
  const last = history[history.length - 1].price;
  if (last < first) return { label: "Trending down", icon: <TrendingDown size={16} /> };
  if (last > first) return { label: "Trending up", icon: <TrendingUp size={16} /> };
  return { label: "Stable", icon: <Minus size={16} /> };
}

const RECOMMENDATION_META: Record<string, { label: string; emoji: string; className: string }> = {
  buy_now: { label: "Buy Now", emoji: "🟢", className: "buy-now" },
  good_price: { label: "Good Price", emoji: "🟡", className: "good-price" },
  wait: { label: "Wait", emoji: "🔴", className: "wait" },
  insufficient_data: { label: "Insufficient Data", emoji: "⚪", className: "insufficient" },
};

function PriceHistorySection({ p }: { p: Product }) {
  const history = p.price_history || [];
  const rec = p.buy_recommendation;
  return (
    <div className="price-history-block">
      <b>Price history</b>
      {history.length < 2 ? (
        <p className="muted">Not enough price history yet. Bella Vista records a new price observation every time this product appears in a search.</p>
      ) : (
        <>
          <div className="chart">
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={history}>
                <XAxis dataKey="date" hide />
                <YAxis hide domain={["dataMin - 300", "dataMax + 300"]} />
                <Tooltip formatter={(v) => formatINR(Number(v))} labelFormatter={(l) => l} />
                <Line type="monotone" dataKey="price" stroke="#b35c3e" strokeWidth={3} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="price-stats">
            <div><small>Current</small><b>{formatINR(rec?.current_price ?? p.price)}</b></div>
            <div><small>Lowest observed</small><b>{formatINR(rec?.lowest_observed_price ?? null)}</b></div>
            <div><small>Highest observed</small><b>{formatINR(rec?.highest_observed_price ?? null)}</b></div>
            <div><small>Average observed</small><b>{formatINR(rec?.average_observed_price ?? null)}</b></div>
            <div><small>Trend</small><b>{trendLabel(history).icon} {trendLabel(history).label}</b></div>
            <div><small>Last updated</small><b>{history[history.length - 1]?.date}</b></div>
          </div>
        </>
      )}
      {rec && (
        <div className={"buy-recommendation " + (RECOMMENDATION_META[rec.status]?.className ?? "")}>
          <span className="rec-emoji">{RECOMMENDATION_META[rec.status]?.emoji}</span>
          <div>
            <b>{RECOMMENDATION_META[rec.status]?.label ?? rec.status}</b>
            <p>{rec.explanation}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function ProductDetail() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const searchId = searchParams.get("search_id") || undefined;
  const [p, setP] = useState<Product | null>(null);
  const [similar, setSimilar] = useState<Product[]>([]);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!id) return;
    setP(null);
    setNotFound(false);

    // Fast path: the product came from a search still held in this browser
    // session, so we already have it AND its sibling results - no extra
    // network round-trip needed for either the product or "similar".
    const cached = findInLastSession(id);
    if (cached) {
      setP(cached.product);
      setSimilar(cached.session.products.filter((item) => item.id !== id));
      return;
    }

    // Fallback path: direct link / refresh. Fetch the product itself, and
    // similar products from its originating search session if we know it.
    getProduct(id)
      .then((product) => {
        setP(product);
        if (searchId) {
          getSimilarFromSearch(searchId, id).then(setSimilar).catch(() => setSimilar([]));
        }
      })
      .catch(() => setNotFound(true));
  }, [id, searchId]);

  if (notFound) {
    return (
      <>
        <Header />
        <main className="loading"><p>We couldn't find that product. It may no longer be available.</p><Link to="/discover">Back to search</Link></main>
      </>
    );
  }
  if (!p) return <><Header /><div className="loading">Loading your pair…</div></>;

  return (
    <>
      <Header />
      <main className="detail">
        <div className="detail-image"><ProductImage p={p} detail /></div>
        <div className="detail-copy">
          <small className="eyebrow">{p.brand ?? "Unknown brand"} {p.store ? `/ ${p.store}` : ""}</small>
          <h1>{p.name}</h1>
          <div className="rating">
            {p.rating != null ? <><Star fill="currentColor" /> {p.rating} {p.review_count != null && <span>· {p.review_count} reviews</span>}</> : <span className="muted">Rating not verified</span>}
          </div>
          <div className="detail-price">
            {formatINR(p.price)}
            {!!p.original_price && p.original_price !== p.price && <del>{formatINR(p.original_price)}</del>}
            {!!p.discount_percent && p.discount_percent > 0 && <b className="discount-pill">-{p.discount_percent}%</b>}
          </div>
          {p.description && <p>{p.description}</p>}
          {p.colors.length > 0 && <div className="tags">{p.colors.map((c) => <span key={c}>{c}</span>)}</div>}
          {p.availability && <div className="availability">Availability: {p.availability.replace(/_/g, " ")}</div>}
          {p.match_reasons.length > 0 && (
            <div className="why-recommend"><b>Why Bella Vista recommends it</b><p>{p.match_reasons.join(" · ")}</p></div>
          )}
          <div className="detail-actions">
            {p.product_url ? (
              <a className="primary" href={p.product_url} target="_blank" rel="noopener noreferrer">
                View / Buy at {p.store ?? "retailer"} <ExternalLink size={16} />
              </a>
            ) : (
              <button className="primary" disabled>Retailer link unavailable</button>
            )}
          </div>
          {p.source === "demo" && <p className="muted small-note">Demo catalog item — not a live web result.</p>}

          <PriceHistorySection p={p} />
        </div>
      </main>
      {similar.length > 0 && (
        <section className="similar-section">
          <div className="section-heading">
            <div><small className="eyebrow">KEEP EXPLORING</small><h2>Similar products</h2><p className="muted">Other results from your search</p></div>
          </div>
          <div className="product-grid">{similar.map((item) => <ProductCard p={item} key={item.id} searchId={searchId} />)}</div>
        </section>
      )}
    </>
  );
}

function About() {
  return (
    <>
      <Header />
      <main className="about">
        <div className="page-title">
          <small className="eyebrow">THE BELLA VISTA METHOD</small>
          <h1>Shopping should feel<br /><i>like being understood.</i></h1>
          <p>Bella Vista is a conversational sneaker finder that searches the live web for real listings, for people who know how they want to feel, even when they don't know the product name.</p>
        </div>
        <div className="about-grid">
          <div><Sparkles /><h2>Talk naturally</h2><p>Say "red and white with gold accents" or "something sportier". Bella Vista understands the details that matter.</p></div>
          <div><Bot /><h2>Get a point of view</h2><p>Every recommendation comes with a reason, so discovery feels personal instead of random.</p></div>
          <div><Heart /><h2>Find your pair</h2><p>We're here to shorten the distance between a feeling and the sneaker that matches it.</p></div>
        </div>
      </main>
    </>
  );
}

function App() {
  const [healthNotice, setHealthNotice] = useState<string | null>(null);
  useEffect(() => {
    getHealth()
      .then((h) => { if (h.mode === "live" && !h.live_available) setHealthNotice("Live search isn't configured yet — showing demo results until an OpenAI API key is set."); })
      .catch(() => {});
  }, []);
  return (
    <>
      {healthNotice && <div className="global-notice">{healthNotice}</div>}
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/discover" element={<Discover />} />
        <Route path="/deals" element={<Listing deal />} />
        <Route path="/product/:id" element={<ProductDetail />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><BrowserRouter><App /></BrowserRouter></React.StrictMode>
);
