/**
 * Quote relay for the website's live prices (Cloudflare Worker).
 *
 * The page asks:   https://<your-worker>.workers.dev/?symbols=TSM
 * The worker asks Finnhub with your secret key, caches each answer for 15 seconds, and returns
 *   { "quotes": [ { "symbol", "price", "change", "pct", "prevClose", "time" } ] }
 * Your Finnhub key never reaches the browser. Only symbols in ALLOWED are relayed.
 *
 * Secrets / settings (Cloudflare dashboard -> Workers -> this worker -> Settings -> Variables):
 *   FINNHUB_KEY     (secret)  your Finnhub API key
 *   ALLOWED_ORIGIN  (text)    your site, e.g. https://yourname.github.io   ("*" while testing)
 */
const ALLOWED = new Set([
  "TSM", "UMC", "ASML", "MU", "INTC", "GFS", "AMAT", "LRCX", "KLAC", "NVDA", "AMD", "QCOM",
  "LIN", "APD", "ENTG", "MP", "SOXX", "URTH",
]);
const MAX_PER_REQUEST = 5;   // Finnhub's free plan allows 60 calls a minute

export default {
  async fetch(request, env, ctx) {
    const cors = {
      "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Content-Type": "application/json",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });
    if (!env.FINNHUB_KEY) return new Response(JSON.stringify({ error: "FINNHUB_KEY is not set" }), { status: 500, headers: cors });

    const url = new URL(request.url);
    const symbols = (url.searchParams.get("symbols") || "").toUpperCase().split(",")
      .map(s => s.trim()).filter(s => ALLOWED.has(s)).slice(0, MAX_PER_REQUEST);
    if (!symbols.length) return new Response(JSON.stringify({ error: "no allowed symbols", allowed: [...ALLOWED] }), { status: 400, headers: cors });

    const cache = caches.default;
    const quotes = await Promise.all(symbols.map(async sym => {
      const key = new Request(`https://quote-cache.internal/${sym}`);
      const hit = await cache.match(key);
      if (hit) return hit.json();
      const r = await fetch(`https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(sym)}&token=${env.FINNHUB_KEY}`);
      if (!r.ok) return { symbol: sym, error: `finnhub ${r.status}` };
      const j = await r.json();
      const q = { symbol: sym, price: j.c, change: j.d, pct: j.dp, prevClose: j.pc, time: j.t };
      ctx.waitUntil(cache.put(key, new Response(JSON.stringify(q), { headers: { "Cache-Control": "max-age=15" } })));
      return q;
    }));
    return new Response(JSON.stringify({ quotes }), { headers: { ...cors, "Cache-Control": "max-age=10" } });
  },
};
