(function () {

document.getElementById("toTracker").onclick = () => document.getElementById("tracker").scrollIntoView();
document.getElementById("tk-toglobe").onclick = () => document.getElementById("globe").scrollIntoView();
const CFG = window.SITE_CONFIG || {};
async function getJSON(u) { const r = await fetch(u, { cache: "no-cache" }); if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }
function ago(iso) {
  if (!iso) return "never"; const t = Date.parse(iso.replace(/Z$/, ":00Z").replace(/:00:00Z$/, ":00Z")); if (!isFinite(t)) return iso;
  const m = Math.round((Date.now() - t) / 60000);
  return m < 2 ? "just now" : m < 90 ? m + " min ago" : m < 36 * 60 ? Math.round(m / 60) + " h ago" : Math.round(m / 1440) + " days ago";
}
function showStatus(st) {
  const el = document.getElementById("tk-status"); if (!el || !st) return;
  const ym = s => s ? new Date(s + "-01T00:00:00Z").toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" }) : "–";
  const parts = [];
  if (st.news) parts.push(`News collected <b>${ago(st.news.asof || st.news.built)}</b>`);
  if (st.prices) parts.push(`Prices through <b>${st.prices.asof}</b>`);
  if (st.risk) parts.push(`Trade data through <b>${ym(st.risk.trade_asof)}</b>`, `Risk index through <b>${ym(st.risk.asof)}</b>`);
  el.innerHTML = parts.map(p => `<span>${p}</span>`).join("");
}
function boot(D) {

// ---------- live quotes (optional: needs the Cloudflare Worker in worker/ and its URL in docs/config.js)
const LIVE_MAP = { "2330.TW": "TSM", "2303.TW": "UMC", "ASML.AS": "ASML" };   // US-listed versions trade live in New York
const liveSym = t => LIVE_MAP[t] || (U[t].currency === "USD" && !t.startsWith("^") ? t : null);
const liveData = {};
function renderLive() {
  const el = document.getElementById("tk-live"); if (!el) return;
  const sym = liveSym(S.t), q = sym && liveData[sym];
  if (!CFG.liveQuotesUrl) { el.innerHTML = `<i class="dot"></i>Live prices are off. Showing daily closes.`; return; }
  if (!sym) { el.innerHTML = `<i class="dot"></i>No free live feed for this listing. Showing the last daily close.`; return; }
  if (!q || !q.price) { el.innerHTML = `<i class="dot"></i>Waiting for a live quote for ${sym}…`; return; }
  const when = q.time ? new Date(q.time * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
  const where = LIVE_MAP[S.t] ? ` ${sym} in New York, USD` : "";
  el.innerHTML = `<i class="dot on"></i>Live${where} <b>${fmtP(q.price)}</b> <span class="${cls(q.pct || 0)}">${fmtSigned(q.change || 0)} (${fmtPct(q.pct || 0)})</span> today <span class="t">${when}</span>`;
}
async function pollLive() {
  const sym = liveSym(S.t);
  if (!CFG.liveQuotesUrl || !sym || document.hidden) return renderLive();
  try {
    const r = await fetch(CFG.liveQuotesUrl.replace(/\/$/, "") + "/?symbols=" + encodeURIComponent(sym));
    const j = await r.json(); (j.quotes || []).forEach(q => liveData[q.symbol] = q);
  } catch (e) { /* relay unreachable: keep the last quote */ }
  renderLive();
}
function startLive() { pollLive(); setInterval(pollLive, 20000); }




const EVENT_INFO = {
  hf_2019: {
    short: "HF '19", title: "Japan curbs HF exports to Korea",
    what: "Japan tightened export controls on hydrogen fluoride (HF), photoresist and fluorinated polyimide shipped to South Korea.",
    link: "HF is the acid fabs use to clean and etch wafers. Korea got about a third of its HF from Japan; within three months China replaced Japan at the same price."
  },
  neon_2022: {
    short: "Neon '22", title: "Russia invades Ukraine",
    what: "The invasion shut Ukraine's neon purifiers in Odesa and Mariupol, a large share of the world's chip-grade neon.",
    link: "Neon is the gas in the lasers that print chip patterns (DUV lithography). Korea's import price rose about 4x before China took over supply."
  },
  gallium_2023: {
    short: "Gallium '23", title: "China licenses gallium exports",
    what: "China announced export licences for gallium and germanium, starting August 1, 2023. China makes almost all of the world's primary gallium.",
    link: "Gallium goes into GaAs radio chips and GaN power chips. Japan and the US imported more right after, a sign of stockpiling, and prices fell."
  },
  helium_2026: {
    short: "Helium '26", title: "Qatar's helium goes offline",
    what: "Strikes in the Gulf took Qatar's Ras Laffan gas complex offline. Qatar supplies about a third of the world's helium.",
    link: "Fabs use helium to cool wafers and purge tools. Qatar supplies 61–85% of the helium for most big chipmakers; US buyers switched to Canada within months."
  }
};
const GROUP_ORDER = ["Foundries & memory", "Equipment", "Chip designers", "Gases & materials", "Rare earths", "Benchmark"];
const GROUP_LABEL = {"Benchmark": "ETFs & indexes"};
const RANGES = ["5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "Max"];
const DAY = 864e5, EPOCH = Date.UTC(2015, 0, 1);
const TK = document.getElementById("tracker");
const css = n => getComputedStyle(TK).getPropertyValue(n).trim();

// ---------- decode
function dec(s, d) { const o = new Array(d.length + 1); let x = s; o[0] = x; for (let i = 0; i < d.length; i++) { x += d[i]; o[i + 1] = x; } return o; }
const RAW = {}; for (const [t, o] of Object.entries(D.p)) RAW[t] = { days: dec(o.s, o.d), c: o.c, v: o.v };
const FX = {}; for (const [k, o] of Object.entries(D.fx)) FX[k] = { days: dec(o.s, o.d), r: o.r };
const U = {}; D.u.forEach(u => U[u.ticker] = u);
const EV = D.ev.map(e => ({ ...e, ...EVENT_INFO[e.key], day: (Date.parse(e.date + "T00:00:00Z") - EPOCH) / DAY }));

const cache = {};
function getSeries(t, usd) {
  const k = t + (usd ? "|USD" : "");
  if (cache[k]) return cache[k];
  const r = RAW[t], cur = U[t].currency;
  let c = r.c;
  if (usd && cur !== "USD" && FX[cur]) {
    const f = FX[cur]; let j = 0;
    c = r.days.map((d, i) => { while (j + 1 < f.days.length && f.days[j + 1] <= d) j++; return r.c[i] * f.r[j]; });
  }
  const ma = n => { const o = new Array(c.length).fill(null); let s = 0; for (let i = 0; i < c.length; i++) { s += c[i]; if (i >= n) s -= c[i - n]; if (i >= n - 1) o[i] = s / n; } return o; };
  return cache[k] = { days: r.days, c, v: r.v, ma5: ma(5), ma10: ma(10), ma20: ma(20), cur: usd ? "USD" : cur };
}
const idxOnOrAfter = (days, day) => { let lo = 0, hi = days.length; while (lo < hi) { const m = (lo + hi) >> 1; if (days[m] < day) lo = m + 1; else hi = m; } return lo; };
const dayToDate = d => new Date(EPOCH + d * DAY);

// ---------- format
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const WD = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
function fmtP(x) {
  if (x == null || !isFinite(x)) return "–";
  const a = Math.abs(x), dp = a >= 1000 ? 2 : a >= 1 ? 2 : 4;
  return x.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
const fmtPct = (x, dp = 2) => (x >= 0 ? "+" : "") + x.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp }) + "%";
const fmtSigned = x => (x >= 0 ? "+" : "−") + fmtP(Math.abs(x));
function fmtVol(v) { if (v == null) return "–"; const a = Math.abs(v); return a >= 1e9 ? (v / 1e9).toFixed(2) + "B" : a >= 1e6 ? (v / 1e6).toFixed(1) + "M" : a >= 1e3 ? (v / 1e3).toFixed(1) + "K" : String(v); }
const fmtDate = d => { const t = dayToDate(d); return `${MON[t.getUTCMonth()]} ${t.getUTCDate()}, ${t.getUTCFullYear()}`; };
const fmtDateLong = d => { const t = dayToDate(d); return `${WD[t.getUTCDay()]}, ${MON[t.getUTCMonth()]} ${t.getUTCDate()} ${t.getUTCFullYear()}`; };
const cls = x => x >= 0 ? "up" : "down";
const unit = (t, cur) => U[t].grp === "Benchmark" && t.startsWith("^") && cur !== "USD" ? "pts" : cur;

// ---------- state
const store = { get(k, d) { try { const v = localStorage.getItem("cst-" + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
                set(k, v) { try { localStorage.setItem("cst-" + k, JSON.stringify(v)); } catch (e) {} } };
const S = {
  t: store.get("t", "2330.TW"), range: store.get("range", "Max"), win: null,
  usd: store.get("usd", false), log: store.get("log", false), ma: store.get("ma", true), ev: store.get("ev", true),
  evSel: "helium_2026", hover: null, tab: "chart"
};
if (!RAW[S.t]) S.t = "2330.TW";
if (!RANGES.includes(S.range)) S.range = "Max";

function view(ser) {
  const n = ser.c.length;
  if (S.win) return { a: Math.max(0, S.win[0]), b: Math.min(n - 1, S.win[1]) };
  if (S.range === "Max") return { a: 0, b: n - 1 };
  if (S.range === "5D") return { a: Math.max(0, n - 5), b: n - 1 };
  const last = dayToDate(ser.days[n - 1]); let cut;
  if (S.range === "YTD") cut = Date.UTC(last.getUTCFullYear(), 0, 1);
  else { const m = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "5Y": 60 }[S.range]; cut = Date.UTC(last.getUTCFullYear(), last.getUTCMonth() - m, last.getUTCDate()); }
  return { a: Math.min(n - 1, idxOnOrAfter(ser.days, (cut - EPOCH) / DAY)), b: n - 1 };
}
function rangeChange(t, usd) { const s = getSeries(t, usd), v = view(s); return { from: s.c[v.a], to: s.c[v.b], pct: 100 * (s.c[v.b] / s.c[v.a] - 1) }; }

// ---------- picker
const groupsEl = document.getElementById("tk-groups"), chipsEl = document.getElementById("tk-chips");
let curGroup = U[S.t].grp;
function renderGroups() {
  groupsEl.innerHTML = "";
  GROUP_ORDER.forEach(g => {
    const b = document.createElement("button"); b.className = "grp"; b.textContent = GROUP_LABEL[g] || g;
    b.setAttribute("aria-pressed", g === curGroup);
    b.onclick = () => { curGroup = g; renderGroups(); renderChips(); };
    groupsEl.appendChild(b);
  });
}
function renderChips() {
  chipsEl.innerHTML = "";
  D.u.filter(u => u.grp === curGroup).forEach(u => {
    const ch = rangeChange(u.ticker, S.usd);
    const b = document.createElement("button"); b.className = "tkchip"; b.setAttribute("aria-pressed", u.ticker === S.t);
    b.innerHTML = `<b>${u.name}</b><small>${u.ticker}</small><span class="chg ${cls(ch.pct)}">${fmtPct(ch.pct, 1)}</span>`;
    b.onclick = () => select(u.ticker);
    chipsEl.appendChild(b);
  });
}
function select(t) { S.t = t; S.hover = null; store.set("t", t); curGroup = U[t].grp; renderAll(); pollLive(); }

// ---------- header
function renderQuote() {
  const u = U[S.t], s = getSeries(S.t, S.usd), v = view(s), n = s.c.length;
  document.getElementById("tk-qname").textContent = u.name;
  const listed = s.days[0] > 60 ? ` · data from ${fmtDate(s.days[0])} (first listed)` : "";
  document.getElementById("tk-qmeta").textContent = `${u.ticker} · ${u.country} · ${GROUP_LABEL[u.grp] || u.grp}${listed}`;
  const i = S.hover != null ? S.hover : v.b, base = s.c[v.a], px = s.c[i];
  document.getElementById("tk-qprice").innerHTML = `${fmtP(px)}<small>${unit(S.t, s.cur)}</small>`;
  const d = px - base, p = 100 * (px / base - 1);
  const lab = S.win ? "around event" : S.range === "Max" ? "since " + fmtDate(s.days[0]) : S.range;
  document.getElementById("tk-qchg").innerHTML = `<span class="${cls(d)}">${fmtSigned(d)} (${fmtPct(p)})</span> <span style="color:var(--muted)">${lab}</span>`;
}

// ---------- ranges & toggles
const rangesEl = document.getElementById("tk-ranges");
function renderRanges() {
  rangesEl.innerHTML = "";
  RANGES.forEach(r => {
    const b = document.createElement("button"); b.className = "rng"; b.textContent = r;
    b.setAttribute("aria-pressed", !S.win && r === S.range);
    b.onclick = () => { S.range = r; S.win = null; S.hover = null; store.set("range", r); renderAll(); };
    rangesEl.appendChild(b);
  });
}
function bindToggle(id, key) {
  const b = document.getElementById(id);
  b.setAttribute("aria-pressed", S[key]);
  b.onclick = () => { S[key] = !S[key]; store.set(key, S[key]); b.setAttribute("aria-pressed", S[key]); renderAll(); };
}
bindToggle("tk-t-ev", "ev"); bindToggle("tk-t-ma", "ma"); bindToggle("tk-t-log", "log"); bindToggle("tk-t-usd", "usd");

// ---------- chart
const cv = document.getElementById("tk-chart"), ctx = cv.getContext("2d");
let G = null; // geometry of last draw, for hit-testing
function draw() {
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  const s = getSeries(S.t, S.usd), { a, b } = view(s);
  // lay out event pills first (two rows if they collide) so the plot can start below them
  const s0 = getSeries(S.t, S.usd), v0 = view(s0), pills = [];
  if (S.ev) {
    ctx.font = `600 11px ${css("--sans")}`;
    const ends = [-1e9, -1e9], span0 = Math.max(1, v0.b - v0.a);
    EV.forEach(e => {
      if (e.day < s0.days[v0.a] || e.day > s0.days[v0.b]) return;
      const i = idxOnOrAfter(s0.days, e.day); if (i > v0.b) return;
      const x = 2 + (i - v0.a) / span0 * (W - 4), w = ctx.measureText(e.short).width + 18;
      const px = Math.min(Math.max(x - w / 2, 2), W - 2 - w);
      const row = px >= ends[0] + 4 ? 0 : 1; ends[row] = px + w;
      pills.push({ e, i, x, px, w, row });
    });
  }
  const rows = pills.some(p => p.row === 1) ? 2 : 1;
  const top = 42 + (rows - 1) * 24, priceBot = Math.round(H * 0.68), volTop = priceBot + 26, volBot = H - 24, L = 2, R = W - 2;
  const span = Math.max(1, b - a), X = i => L + (i - a) / span * (R - L);
  let lo = Infinity, hi = -Infinity, iLo = a, iHi = a;
  for (let i = a; i <= b; i++) { const c = s.c[i]; if (c < lo) { lo = c; iLo = i; } if (c > hi) { hi = c; iHi = i; } }
  let ylo = lo, yhi = hi;
  if (S.ma) for (let i = a; i <= b; i++) for (const m of [s.ma5, s.ma10, s.ma20]) { const v = m[i]; if (v != null) { if (v < ylo) ylo = v; if (v > yhi) yhi = v; } }
  const useLog = S.log && ylo > 0;
  const tf = v => useLog ? Math.log(v) : v;
  let t0 = tf(ylo), t1 = tf(yhi); if (t1 - t0 < 1e-9) { t0 -= 1; t1 += 1; }
  const pad = (t1 - t0) * 0.04; t0 -= pad; t1 += pad;
  const Y = v => priceBot - (tf(v) - t0) / (t1 - t0) * (priceBot - top);
  const base = s.c[a], last = s.c[b], upCol = css("--up"), dnCol = css("--down");
  const col = last >= base ? upCol : dnCol;

  // area + line
  ctx.beginPath();
  for (let i = a; i <= b; i++) { const x = X(i), y = Y(s.c[i]); i === a ? ctx.moveTo(x, y) : ctx.lineTo(x, y); }
  const linePath = new Path2D(); for (let i = a; i <= b; i++) { const x = X(i), y = Y(s.c[i]); i === a ? linePath.moveTo(x, y) : linePath.lineTo(x, y); }
  ctx.lineTo(X(b), priceBot); ctx.lineTo(X(a), priceBot); ctx.closePath();
  const gr = ctx.createLinearGradient(0, top, 0, priceBot); gr.addColorStop(0, hexA(col, .32)); gr.addColorStop(1, hexA(col, .02));
  ctx.fillStyle = gr; ctx.fill();
  ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.lineJoin = "round"; ctx.stroke(linePath);

  // moving averages
  if (S.ma) [[s.ma20, "--ma20"], [s.ma10, "--ma10"], [s.ma5, "--ma5"]].forEach(([m, c]) => {
    ctx.beginPath(); let on = false;
    for (let i = a; i <= b; i++) { const v = m[i]; if (v == null) { on = false; continue; } const x = X(i), y = Y(v); on ? ctx.lineTo(x, y) : ctx.moveTo(x, y); on = true; }
    ctx.strokeStyle = css(c); ctx.lineWidth = 1.1; ctx.stroke();
  });

  // volume
  if (s.v) {
    let vmax = 0; for (let i = a; i <= b; i++) vmax = Math.max(vmax, s.v[i] || 0);
    const bw = Math.max(1, (R - L) / (span + 1) * 0.7);
    for (let i = a; i <= b; i++) {
      const v = s.v[i] || 0; if (!vmax || !v) continue;
      const h = v / vmax * (volBot - volTop), up = i === 0 || s.c[i] >= s.c[i - 1];
      ctx.fillStyle = hexA(up ? upCol : dnCol, .75); ctx.fillRect(X(i) - bw / 2, volBot - h, bw, h);
    }
  } else {
    ctx.fillStyle = css("--faint"); ctx.font = `11px ${css("--sans")}`; ctx.textAlign = "left";
    ctx.fillText("No volume reported for this index", L + 4, (volTop + volBot) / 2);
  }
  ctx.strokeStyle = css("--line"); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(L, volBot + .5); ctx.lineTo(R, volBot + .5); ctx.stroke();

  // last price dashed line + tag
  const yl = Y(last);
  ctx.setLineDash([5, 5]); ctx.strokeStyle = hexA(col, .7); ctx.beginPath(); ctx.moveTo(L, yl); ctx.lineTo(R, yl); ctx.stroke(); ctx.setLineDash([]);
  ctx.font = `500 13px ${css("--mono")}`; const tag = fmtP(last), tw = ctx.measureText(tag).width + 14;
  const ty = Math.min(priceBot - 12, Math.max(top - 2, yl));
  roundRect(R - tw, ty - 12, tw, 24, 6); ctx.fillStyle = css("--panel-2"); ctx.fill(); ctx.strokeStyle = css("--line"); ctx.stroke();
  ctx.fillStyle = css("--ink"); ctx.textAlign = "right"; ctx.textBaseline = "middle"; ctx.fillText(tag, R - 7, ty + 1);

  // high / low labels
  ctx.textBaseline = "alphabetic"; ctx.textAlign = "left"; ctx.font = `500 12px ${css("--mono")}`;
  const hiTxt = `${fmtP(hi)}  ${fmtPct(100 * (hi / base - 1))}`, loTxt = `${fmtP(lo)}  ${fmtPct(100 * (lo / base - 1))}`;
  ctx.fillStyle = hexA(upCol, .95); ctx.fillText("H " + hiTxt, L + 4, Math.max(top - 6, Y(hi) - 6));
  ctx.fillStyle = hexA(lo < base ? dnCol : upCol, .95); ctx.fillText("L " + loTxt, L + 4, Math.min(priceBot + 17, Y(lo) + 17));

  // events
  const hits = [];
  ctx.font = `600 11px ${css("--sans")}`; ctx.textBaseline = "middle";
  pills.forEach(({ e, x, px, w, row }) => {
    const sel = e.key === S.evSel, py = 4 + row * 24;
    ctx.strokeStyle = hexA(css("--event"), sel ? .95 : .6); ctx.lineWidth = sel ? 1.4 : 1; ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(x, py + 20); ctx.lineTo(x, volBot); ctx.stroke(); ctx.setLineDash([]);
    roundRect(px, py, w, 20, 10); ctx.fillStyle = sel ? css("--event") : css("--panel-2"); ctx.fill();
    ctx.strokeStyle = hexA(css("--event"), .8); ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = sel ? css("--bg") : css("--event"); ctx.textAlign = "center"; ctx.fillText(e.short, px + w / 2, py + 10.5);
    hits.push({ key: e.key, x, px, w, py });
  });

  // x labels
  ctx.fillStyle = css("--muted"); ctx.font = `12px ${css("--mono")}`; ctx.textBaseline = "alphabetic";
  const nl = W < 480 ? 3 : 5, longR = s.days[b] - s.days[a] > 400;
  for (let k = 0; k < nl; k++) {
    const i = Math.round(a + (b - a) * (k + 0.5) / nl), d = dayToDate(s.days[i]);
    const txt = longR ? `${MON[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}` : `${String(d.getUTCMonth() + 1).padStart(2, "0")}/${String(d.getUTCDate()).padStart(2, "0")}`;
    ctx.textAlign = "center"; ctx.fillText(txt, X(i), H - 6);
  }

  // crosshair
  if (S.hover != null && S.hover >= a && S.hover <= b) {
    const i = S.hover, x = X(i), y = Y(s.c[i]);
    ctx.strokeStyle = hexA(css("--ink"), .45); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x + .5, top - 8); ctx.lineTo(x + .5, volBot); ctx.moveTo(L, y + .5); ctx.lineTo(R, y + .5); ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill(); ctx.strokeStyle = css("--bg"); ctx.lineWidth = 2; ctx.stroke();
  }
  G = { a, b, X, L, R, hits, top, volBot, span };
}
function hexA(hex, al) { const h = hex.replace("#", ""); const n = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${al})`; }
function roundRect(x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }

function renderLegend() {
  const s = getSeries(S.t, S.usd), v = view(s), i = S.hover != null ? S.hover : v.b;
  document.getElementById("tk-legend").innerHTML = S.ma
    ? `<span>MA(5,10,20)</span><span class="m5">MA5:${fmtP(s.ma5[i])}</span><span class="m10">MA10:${fmtP(s.ma10[i])}</span><span class="m20">MA20:${fmtP(s.ma20[i])}</span>`
    : `<span>Moving averages hidden</span>`;
  const prev = i > 0 ? s.c[i - 1] : null, dp = prev ? 100 * (s.c[i] / prev - 1) : null;
  document.getElementById("tk-readout").innerHTML =
    `<span>${S.hover != null ? "" : "Last close · "}<b>${fmtDateLong(s.days[i])}</b></span>` +
    `<span>Close <b>${fmtP(s.c[i])}</b></span>` +
    (dp != null ? `<span>Day <b class="${cls(dp)}">${fmtPct(dp)}</b></span>` : "") +
    `<span>Vol <b>${s.v ? fmtVol(s.v[i]) : "–"}</b></span>`;
}

function pointerIdx(ev) {
  const r = cv.getBoundingClientRect(), x = ev.clientX - r.left;
  if (!G) return null;
  return Math.max(G.a, Math.min(G.b, Math.round(G.a + (x - G.L) / (G.R - G.L) * G.span)));
}
cv.addEventListener("pointermove", ev => { S.hover = pointerIdx(ev); draw(); renderLegend(); renderQuote(); });
cv.addEventListener("pointerleave", () => { S.hover = null; draw(); renderLegend(); renderQuote(); });
cv.addEventListener("click", ev => {
  if (!G) return; const r = cv.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
  const h = G.hits.find(h => (y >= h.py && y <= h.py + 20 && x >= h.px && x <= h.px + h.w) || (y > G.top - 10 && Math.abs(x - h.x) <= 8));
  if (h) { S.evSel = h.key; renderEvent(); draw(); }
});

// ---------- events
function evStats(t, e) {
  const s = getSeries(t, false), i0 = idxOnOrAfter(s.days, e.day);
  if (i0 === 0 || i0 >= s.c.length) return null;
  const pre = s.c[i0 - 1], at = k => i0 + k < s.c.length ? 100 * (s.c[i0 + k] / pre - 1) : null;
  const r = (D.react[e.key] || {})[t];
  return { i0, p5: at(5), p20: at(20), ar5: r ? r.d5 : null, ar20: r ? r.d20 : null };
}
const statCell = (label, val, sub) => `<div class="stat"><span>${label}</span><b class="${val == null ? "" : cls(val)}">${val == null ? "–" : fmtPct(val, 1)}</b><em>${sub || "&nbsp;"}</em></div>`;
const tsub = x => x ? `t = ${x[1].toFixed(1)}${Math.abs(x[1]) >= 1.96 ? " *" : ""}` : "";
function roleTag(t, e) {
  const r = e.role[t];
  return r === "loser" ? `<span class="role loser">Expected loser</span>` : r === "winner" ? `<span class="role winner">Expected winner</span>` : `<span class="role">Not in a test group</span>`;
}
function renderEvChips() {
  const el = document.getElementById("tk-evchips"), s = getSeries(S.t, S.usd), v = view(s);
  el.innerHTML = "";
  EV.forEach(e => {
    const inView = e.day >= s.days[v.a] && e.day <= s.days[v.b];
    const b = document.createElement("button"); b.className = "evchip" + (inView ? "" : " out");
    b.setAttribute("aria-pressed", e.key === S.evSel);
    b.innerHTML = `<i></i>${e.title}<small>${e.date.slice(0, 7)}</small>`;
    b.onclick = () => { S.evSel = e.key; renderEvent(); renderEvChips(); draw(); };
    el.appendChild(b);
  });
}
function renderEvent() {
  const e = EV.find(x => x.key === S.evSel), st = evStats(S.t, e), u = U[S.t];
  let body;
  if (!st) body = `<p>${u.name} was not trading yet on this date (data starts ${fmtDate(RAW[S.t].days[0])}).</p>`;
  else body = `<div class="stats">
      ${statCell("Price, 5 days", st.p5, "raw move")}
      ${statCell("Price, 20 days", st.p20, "raw move")}
      ${statCell("Abnormal, 5 days", st.ar5 && st.ar5[0], tsub(st.ar5) || "vs world market")}
      ${statCell("Abnormal, 20 days", st.ar20 && st.ar20[0], tsub(st.ar20) || "vs world market")}
    </div>`;
  document.getElementById("tk-evcard").innerHTML = `
    <div class="when">${fmtDateLong(e.day)}</div>
    <h3>${e.title}</h3>
    <p>${e.what}</p>
    <div class="lbl">Supply-chain link</div>
    <p>${e.link}</p>
    <div class="evactions"><span class="lbl">${u.name}</span>${roleTag(S.t, e)}</div>
    ${body}
    <div class="evactions">
      ${st ? `<button class="btn" id="tk-zoom">Zoom chart to this event</button>` : ""}
      ${S.win ? `<button class="btn ghost" id="tk-unzoom">Back to ${S.range}</button>` : ""}
    </div>`;
  const z = document.getElementById("tk-zoom"); if (z) z.onclick = () => { S.win = [st.i0 - 60, st.i0 + 60]; S.hover = null; renderAll(); };
  const uz = document.getElementById("tk-unzoom"); if (uz) uz.onclick = () => { S.win = null; renderAll(); };
}
function renderEvTable() {
  const rows = EV.map(e => {
    const st = evStats(S.t, e);
    const c = (v, sub) => v == null ? `<td class="r num">–</td>` : `<td class="r num ${cls(v)}">${fmtPct(v, 1)}${sub || ""}</td>`;
    if (!st) return `<tr data-ev="${e.key}"><td>${e.title}<br><small style="color:var(--muted)">${fmtDate(e.day)}</small></td><td>–</td><td class="r" colspan="4" style="color:var(--muted)">Not trading yet</td></tr>`;
    const star = x => x && Math.abs(x[1]) >= 1.96 ? "*" : "";
    return `<tr data-ev="${e.key}"><td>${e.title}<br><small style="color:var(--muted)">${fmtDate(e.day)}</small></td><td>${roleTag(S.t, e)}</td>
      ${c(st.p5)}${c(st.p20)}${c(st.ar5 && st.ar5[0], star(st.ar5))}${c(st.ar20 && st.ar20[0], star(st.ar20))}</tr>`;
  }).join("");
  const t = document.getElementById("tk-evtable");
  t.innerHTML = `<thead><tr><th>Event</th><th>Role</th><th class="r">Price 5d</th><th class="r">Price 20d</th><th class="r">Abnormal 5d</th><th class="r">Abnormal 20d</th></tr></thead><tbody>${rows}</tbody>`;
  t.querySelectorAll("tbody tr").forEach(tr => tr.onclick = () => { S.evSel = tr.dataset.ev; setTab("chart"); renderAll(); });
}

// ---------- peers
function spark(t) {
  const s = getSeries(t, S.usd), v = view(s), n = Math.min(80, v.b - v.a + 1), pts = [];
  let lo = Infinity, hi = -Infinity; const idx = [];
  for (let k = 0; k < n; k++) { const i = Math.round(v.a + (v.b - v.a) * k / Math.max(1, n - 1)); idx.push(i); lo = Math.min(lo, s.c[i]); hi = Math.max(hi, s.c[i]); }
  idx.forEach((i, k) => pts.push(`${(k / Math.max(1, n - 1) * 96 + 2).toFixed(1)},${(26 - (s.c[i] - lo) / ((hi - lo) || 1) * 22).toFixed(1)}`));
  const up = s.c[v.b] >= s.c[v.a];
  return `<svg width="100" height="30" viewBox="0 0 100 30" aria-hidden="true"><polyline fill="none" stroke="${up ? css("--up") : css("--down")}" stroke-width="1.5" points="${pts.join(" ")}"/></svg>`;
}
function oneYear(t) { const s = getSeries(t, S.usd), n = s.c.length, last = dayToDate(s.days[n - 1]); const i = idxOnOrAfter(s.days, (Date.UTC(last.getUTCFullYear() - 1, last.getUTCMonth(), last.getUTCDate()) - EPOCH) / DAY); return i === 0 && s.days[0] > s.days[n - 1] - 365 ? null : 100 * (s.c[n - 1] / s.c[i] - 1); }
function renderPeers() {
  const g = U[S.t].grp, lab = S.win ? "Event window" : S.range;
  const rows = D.u.filter(u => u.grp === g).map(u => {
    const s = getSeries(u.ticker, S.usd), ch = rangeChange(u.ticker, S.usd), y1 = oneYear(u.ticker);
    return `<tr data-t="${u.ticker}" class="${u.ticker === S.t ? "sel" : ""}"><td><b>${u.name}</b><br><small class="num" style="color:var(--muted)">${u.ticker}</small></td>
      <td class="r num">${fmtP(s.c[s.c.length - 1])} <small style="color:var(--muted)">${unit(u.ticker, s.cur)}</small></td>
      <td class="r num ${cls(ch.pct)}">${fmtPct(ch.pct, 1)}</td><td class="r num ${y1 == null ? "" : cls(y1)}">${y1 == null ? "–" : fmtPct(y1, 1)}</td><td>${spark(u.ticker)}</td></tr>`;
  }).join("");
  const t = document.getElementById("tk-peertable");
  t.innerHTML = `<thead><tr><th>${GROUP_LABEL[g] || g}</th><th class="r">Last</th><th class="r">${lab}</th><th class="r">1Y</th><th>${lab}</th></tr></thead><tbody>${rows}</tbody>`;
  t.querySelectorAll("tbody tr").forEach(tr => tr.onclick = () => select(tr.dataset.t));
}

// ---------- tabs
function setTab(k) {
  S.tab = k;
  ["chart", "events", "peers"].forEach(x => { document.getElementById("tk-tab-" + x).setAttribute("aria-selected", x === k); document.getElementById("tk-pane-" + x).hidden = x !== k; });
  if (k === "chart") requestAnimationFrame(draw);
}
TK.querySelectorAll(".tab").forEach(b => b.onclick = () => setTab(b.dataset.tab));

function renderAll() {
  renderGroups(); renderChips(); renderQuote(); renderLive(); renderRanges(); renderLegend(); renderEvChips(); renderEvent(); renderEvTable(); renderPeers();
  if (S.tab === "chart") draw();
}
document.getElementById("tk-asof").textContent = `Daily closes through ${fmtDate((Date.parse(D.asof + "T00:00:00Z") - EPOCH) / DAY)}`;
document.getElementById("tk-srcline").textContent = `${D.u.length - 8} companies and 8 benchmarks · Jan 2015 to ${D.asof} · four supply shocks from the research project's event studies (phase 8, Model 4).`;
new ResizeObserver(() => { if (S.tab === "chart") draw(); }).observe(cv);
renderAll();
if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);

startLive();
}

(async () => {
  const msg = document.getElementById("tk-loading");
  getJSON("data/status.json").then(showStatus).catch(() => {});
  setInterval(() => getJSON("data/status.json").then(showStatus).catch(() => {}), 5 * 60 * 1000);
  try {
    const meta = await getJSON("data/meta.json");
    const res = await Promise.allSettled([getJSON("data/fx.json"), ...meta.u.map(u => getJSON("data/prices/" + meta.files[u.ticker] + ".json"))]);
    if (res[0].status !== "fulfilled") throw new Error("exchange rates missing");
    const p = {}; meta.u.forEach((u, i) => { if (res[i + 1].status === "fulfilled") p[u.ticker] = res[i + 1].value; });
    meta.u = meta.u.filter(u => p[u.ticker]);
    msg.hidden = true;
    boot({ ...meta, p, fx: res[0].value });
  } catch (e) {
    msg.textContent = "Could not load price data (" + e.message + "). If you opened this file directly from your computer, view it through the website instead.";
  }
})();

})();
