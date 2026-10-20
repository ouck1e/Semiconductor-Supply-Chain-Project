/* Agent Trading Desk: reads data.json (built by agent_dashboard.py) and draws the agents' trades on real prices.
   Simulation only. Nothing here places an order. */
"use strict";

const C = { price: "#c9d2df", up: "#3ccf95", down: "#f0566f", blue: "#3b7bfa", ref: "#8a93a1", grid: "#232a34", line: "#2c3440", ink2: "#a3acba" };
const $ = s => document.querySelector(s);
const h = (tag, attrs = {}, ...kids) => { const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === "text") e.textContent = v; else if (k === "html") e.innerHTML = v; else e.setAttribute(k, v); }
  kids.flat().forEach(k => k != null && e.append(k)); return e; };
const pct = (x, d = 2) => x == null || isNaN(x) ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d) + "%";
const pts = (x, d = 2) => x == null || isNaN(x) ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d);
const usd = (x, d) => x == null ? "–" : "$" + x.toLocaleString("en-US", { minimumFractionDigits: d ?? (x < 100 ? 2 : 2), maximumFractionDigits: d ?? (x < 10 ? 3 : 2) });
const sign = x => x > 0 ? "pos" : x < 0 ? "neg" : "";
const store = { get(k) { try { return localStorage.getItem("desk." + k); } catch { return null; } },
                set(k, v) { try { localStorage.setItem("desk." + k, v); } catch { /* storage off */ } } };

let D, FEE, SLIP;                         // data, per-side fee and slippage (fractions)
const S = { stock: null, version: "all", runId: null, frames: [], idx: 0, playing: false, timer: null };
let priceChart, priceSeries, eqChart, eqTeam, eqHold, priceLines = [];

/* ---------- data helpers ---------- */
const stockRuns = () => D.runs.filter(r => r.ticker === S.stock && (S.version === "all" || r.version === S.version))
  .sort((a, b) => a.decision_date.localeCompare(b.decision_date) || a.version.localeCompare(b.version));
const run = () => D.runs.find(r => r.run_id === S.runId);
const series = t => { const st = D.stocks[t]; return st.dates.map((d, i) => ({ time: d, value: st.close[i] })); };
const idxOf = (t, date) => { const ds = D.stocks[t].dates; let lo = 0, hi = ds.length - 1; // last index with date <= target
  if (date < ds[0]) return 0; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (ds[m] <= date) lo = m; else hi = m - 1; } return lo; };
const closeAt = (t, date) => D.stocks[t].close[idxOf(t, date)];
const netRet = (entry, px) => ((px * (1 - SLIP)) / (entry * (1 + SLIP)) - 1 - 2 * FEE) * 100;
const windowEnd = r => { const st = D.stocks[r.ticker]; const e = idxOf(r.ticker, r.entry_date || r.decision_date);
  const last = r.exit_date ? idxOf(r.ticker, r.exit_date) : e; return Math.min(st.dates.length - 1, Math.max(last, e + (r.hold_days || D.config.max_hold))); };

/* ---------- charts ---------- */
function makeCharts() {
  const base = { autoSize: true, layout: { background: { type: "solid", color: "transparent" }, textColor: C.ink2, fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
    grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } }, rightPriceScale: { borderColor: C.line }, timeScale: { borderColor: C.line },
    crosshair: { mode: 0 }, handleScroll: true, handleScale: true };
  priceChart = LightweightCharts.createChart($("#price-chart"), base);
  priceSeries = priceChart.addLineSeries({ color: C.price, lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
    priceFormat: { type: "price", precision: 2, minMove: 0.01 } });
  priceChart.subscribeClick(p => { if (!p.time) return; const t = typeof p.time === "string" ? p.time : null; if (!t) return;
    const hit = stockRuns().find(r => [r.decision_date, r.entry_date, r.exit_date].includes(t)); if (hit) select(hit.run_id, true); });
  eqChart = LightweightCharts.createChart($("#equity-chart"), { ...base, handleScroll: false, handleScale: false });
  eqHold = eqChart.addLineSeries({ color: C.ref, lineWidth: 2, priceLineVisible: false });
  eqTeam = eqChart.addLineSeries({ color: C.blue, lineWidth: 2, priceLineVisible: false });
}

function markersUpTo(date) {
  const m = [];
  stockRuns().forEach(r => { const sel = r.run_id === S.runId, size = sel ? 2 : 1;
    if (r.action === "BUY") {
      if (r.entry_date && (!date || r.entry_date <= date)) m.push({ time: r.entry_date, position: "belowBar", shape: "arrowUp", color: C.up, size, text: `${r.version} BUY` });
      if (r.exit_date && r.status === "scored" && (!date || r.exit_date <= date)) m.push({ time: r.exit_date, position: "aboveBar", shape: "arrowDown", color: C.down, size, text: `SELL · ${r.exit_reason}` });
    } else if (!date || r.decision_date <= date) {
      m.push({ time: r.decision_date, position: "aboveBar", shape: "circle", color: C.ref, size, text: `${r.version} skip` });
    } });
  return m.sort((a, b) => a.time.localeCompare(b.time));
}

function drawLevels(r, upTo) {
  priceLines.forEach(l => priceSeries.removePriceLine(l)); priceLines = [];
  if (!r || r.action !== "BUY" || !r.entry_px || (upTo && upTo < r.entry_date)) return;
  const line = (price, color, title) => price && priceLines.push(priceSeries.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }));
  line(r.target_px, C.up, "target"); line(r.stop_px, C.down, "stop"); line(r.entry_px, C.blue, "entry");
}

function focusRange(r) {
  const st = D.stocks[r.ticker], a = Math.max(0, idxOf(r.ticker, r.decision_date) - 70), b = Math.min(st.dates.length - 1, windowEnd(r) + 25);
  priceChart.timeScale().setVisibleRange({ from: st.dates[a], to: st.dates[b] });
}

function drawEquity(r, upTo) {
  if (!r) { eqTeam.setData([]); eqHold.setData([]); return; }
  const st = D.stocks[r.ticker], e = idxOf(r.ticker, r.entry_date || r.decision_date), end = windowEnd(r);
  const exitI = r.action === "BUY" && r.exit_date ? idxOf(r.ticker, r.exit_date) : null, e0 = st.close[e];
  const team = [], hold = [];
  for (let i = e; i <= end; i++) { const d = st.dates[i]; if (upTo && d > upTo) break;
    hold.push({ time: d, value: +(100 * st.close[i] / e0).toFixed(3) });
    let v = 100; if (r.action === "BUY") { const j = exitI != null ? Math.min(i, exitI) : i; v = 100 + (i === e ? -0.2 : netRet(e0, st.close[j])); }
    team.push({ time: d, value: +v.toFixed(3) }); }
  eqHold.setData(hold); eqTeam.setData(team); eqChart.timeScale().fitContent();
}

/* ---------- panels ---------- */
function tiles(r, upTo) {
  const t = S.stock, date = upTo || (r ? D.stocks[t].dates[windowEnd(r)] : D.stocks[t].dates.at(-1)), px = closeAt(t, date);
  $("#t-price").textContent = usd(px); $("#t-price-note").textContent = `close on ${D.stocks[t].dates[idxOf(t, date)]} (USD)`;
  const set = (id, v, note, cls = "") => { const el = $(id); el.textContent = v; el.className = "big " + cls; $(id + "-note").textContent = note; };
  if (!r) { ["#t-team", "#t-hold", "#t-pos"].forEach(id => set(id, "–", "")); }
  else {
    const started = date >= (r.entry_date || r.decision_date), e0 = r.entry_px || closeAt(t, r.entry_date || r.decision_date);
    // Holding is judged over the same window as the decision (entry to max hold), with the scorer's costs.
    const wEnd = D.stocks[t].dates[windowEnd(r)], holdDate = date < wEnd ? date : wEnd;
    const holdNow = started ? netRet(e0, closeAt(t, holdDate)) : null;
    if (r.action !== "BUY") set("#t-team", "0.00%", "skipped: no position", "");
    else if (!started) set("#t-team", "waiting", `buys at the close on ${r.entry_date}`);
    else { const closed = r.status === "scored" && date >= r.exit_date; const v = closed ? r.ret : netRet(e0, px);
      set("#t-team", pct(v), closed ? `closed: ${r.exit_reason}` : "open, fees included", sign(v)); }
    set("#t-hold", started ? pct(holdNow) : "–", started ? `${r.entry_date || r.decision_date} to ${holdDate}` : "starts at entry", sign(holdNow));
    const open = r.action === "BUY" && started && !(r.status === "scored" && date >= r.exit_date);
    const value = open ? D.config.portfolio * r.size / 100 * (1 + netRet(e0, px) / 100) : 0;
    set("#t-pos", open ? usd(value, 0) : "flat", open ? `${r.size}% of $${(D.config.portfolio / 1000).toFixed(0)}k · stop ${usd(r.stop_px)} · target ${usd(r.target_px)}` : r.action === "BUY" ? "no open position on this date" : "the team stayed out");
  }
  const buys = stockRuns().filter(x => x.action === "BUY" && x.status === "scored"), won = buys.filter(x => x.ret > 0).length;
  set("#t-count", String(buys.length), `${won} won, ${buys.length - won} lost · ${stockRuns().length} decisions`);
}

function signal(r) {
  const box = $("#signal-box"), rows = $("#signal-rows"), why = $("#why"); box.innerHTML = ""; rows.innerHTML = ""; why.innerHTML = "";
  if (!r) { box.append(h("p", { text: "No decisions on this stock for the chosen version." })); return; }
  const buy = r.action === "BUY";
  box.append(h("div", { class: "head " + (buy ? "buy" : "skip") }, h("b", { text: buy ? "BUY" : "SKIP" }), h("span", { text: `${r.version} · ${r.decision_date}` })),
    h("p", { text: buy ? `Bought ${r.size}% at the next close. Sells at a ${r.stop}% stop, a ${r.target}% target or after ${r.hold_days} trading days.`
                       : r.plan.action === "BUY" ? `The Strategist proposed a buy; the team did not take it (${r.risk_decision.toLowerCase()}).` : "No setup the team was willing to trade." }));
  const add = (k, v, cls = "") => rows.append(h("dt", { text: k }), h("dd", { class: cls, text: v }));
  add("Set", r.eval_set ? `${r.eval_set} (${r.split})` : r.split); add("Blind run", r.blind ? "yes" : "no, real name");
  if (r.plan.action === "BUY") add("Strategist plan", `${r.plan.size}% · −${r.plan.stop}% / +${r.plan.target}%`); else add("Strategist plan", "no setup");
  add("Risk Manager", r.risk_decision || "–");
  if (r.applied_fix && !/^none$/i.test(r.applied_fix)) add("Fix applied", r.applied_fix);
  if (buy) { add("Entry", `${usd(r.entry_px)} on ${r.entry_date}`); add("Exit", r.status === "scored" ? `${usd(r.exit_px)} on ${r.exit_date} (${r.exit_reason})` : "still open"); }
  add("Team result", pct(r.ret), sign(r.ret)); add("Holding instead", pct(r.hold_ret), sign(r.hold_ret));
  add("vs holding", pts(r.vs_hold), sign(r.vs_hold)); add("vs phase 8 rule", pts(r.vs_baseline), sign(r.vs_baseline));
  if (r.vetoed === "yes") add("Veto", r.veto_right === "yes" ? `right (plan would have made ${pct(r.plan.ret)})` : `wrong (plan would have made ${pct(r.plan.ret)})`);
  [["Researcher", r.researcher], ["Strategist", r.strategist], ["Risk Manager", r.risk_manager], ["Boss", r.boss]].forEach(([k, v]) =>
    why.append(h("div", {}, h("h3", { text: k }), h("p", { text: v || "Not saved for this run." }))));
}

function events(r) {
  if (!r) return [];
  const ev = [];
  ev.push([r.decision_date, "PLAN", r.plan.action === "BUY" ? `Strategist: BUY ${r.plan.size}%, stop −${r.plan.stop}%, target +${r.plan.target}%` : "Strategist: no setup, NO TRADE"]);
  ev.push([r.decision_date, "INFO", `Risk Manager: ${r.risk_decision || "–"}`]);
  ev.push([r.decision_date, r.action === "BUY" ? "BUY" : "SKIP", `Boss: ${r.final}`]);
  if (r.action === "BUY") {
    ev.push([r.entry_date, "BUY", `Filled ${r.size}% at ${usd(r.entry_px)} (next close)`]);
    if (r.status === "scored") ev.push([r.exit_date, "SELL", `Sold at ${usd(r.exit_px)}: ${r.exit_reason} · ${pct(r.ret)}`]);
  } else if (r.exit_date) ev.push([r.exit_date, "INFO", `Window closed: holding would have made ${pct(r.hold_ret)} (${r.good_skip === "yes" ? "good skip" : "missed gain"})`]);
  return ev;
}

function activity(r, upTo) {
  const ol = $("#log"); ol.innerHTML = "";
  const ev = events(r).filter(e => !upTo || e[0] <= upTo).reverse();
  if (!ev.length) { ol.append(h("li", {}, h("time", { text: "" }), h("span", { class: "k INFO", text: "INFO" }), h("span", { text: upTo ? "Nothing yet. Replay is before the decision day." : "No decision selected." }))); return; }
  ev.forEach(([d, k, t]) => ol.append(h("li", {}, h("time", { text: d }), h("span", { class: "k " + k, text: k }), h("span", { text: t }))));
}

function runsTable() {
  const t = $("#runs"); t.innerHTML = "";
  t.append(h("thead", {}, h("tr", {}, ...["Decided", "Version", "Set", "Decision", "Result", "Holding", "vs holding"].map((x, i) => h("th", { class: i > 3 ? "n" : "", text: x })))));
  const tb = h("tbody"); const rs = stockRuns();
  if (!rs.length) tb.append(h("tr", {}, h("td", { colspan: "7", class: "empty", text: "No decisions on this stock for the chosen version." })));
  rs.forEach(r => { const tr = h("tr", { class: "run", tabindex: "0", "aria-selected": String(r.run_id === S.runId) },
      h("td", { class: "mono", text: r.decision_date }), h("td", { class: "mono", text: r.version }), h("td", { text: r.eval_set || r.split }),
      h("td", {}, h("span", { class: "tag" + (r.action === "BUY" ? " buy" : ""), text: r.action === "BUY" ? `BUY · ${r.exit_reason || "open"}` : "skip" })),
      h("td", { class: "n " + sign(r.ret), text: r.status === "pending" ? pct(r.mark_pct) + " open" : pct(r.ret) }), h("td", { class: "n", text: pct(r.hold_ret) }),
      h("td", { class: "n " + sign(r.vs_hold), text: pts(r.vs_hold) }));
    const go = () => select(r.run_id, true); tr.addEventListener("click", go); tr.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    tb.append(tr); });
  t.append(tb);
}

/* ---------- replay ---------- */
function setupFrames(r) {
  stop(); const st = D.stocks[S.stock]; if (!r) { S.frames = []; return; }
  const a = Math.max(0, idxOf(r.ticker, r.decision_date) - 40), b = Math.min(st.dates.length - 1, windowEnd(r) + 10);
  S.frames = st.dates.slice(a, b + 1); const sc = $("#scrub"); sc.max = String(S.frames.length - 1); sc.value = sc.max; $("#scrub-date").textContent = "";
}
function frame(i) {
  const r = run(); if (!r || !S.frames.length) return; S.idx = i; const date = S.frames[i];
  const full = series(S.stock); const cut = full.filter(p => p.time <= date);
  priceSeries.setData(cut); priceSeries.setMarkers(markersUpTo(date)); drawLevels(r, date);
  priceChart.timeScale().setVisibleRange({ from: S.frames[0], to: S.frames.at(-1) });
  drawEquity(r, date); tiles(r, date); activity(r, date);
  $("#scrub").value = String(i); $("#scrub-date").textContent = date;
}
function play() {
  if (!S.frames.length) return; if (S.idx >= S.frames.length - 1 || !S.playing && $("#scrub").value === $("#scrub").max) S.idx = 0;
  S.playing = true; $("#play").textContent = "❚❚ Pause";
  const step = () => { frame(S.idx); if (S.idx >= S.frames.length - 1) { stop(); return; } S.idx++; S.timer = setTimeout(step, +$("#speed").value); };
  step();
}
function stop() { clearTimeout(S.timer); S.playing = false; $("#play").textContent = "▶ Replay trade"; }
function showAll() { stop(); const r = run(); priceSeries.setData(series(S.stock)); priceSeries.setMarkers(markersUpTo(null)); drawLevels(r);
  if (r) focusRange(r); else priceChart.timeScale().fitContent(); drawEquity(r); tiles(r); activity(r);
  if (S.frames.length) { $("#scrub").value = $("#scrub").max; $("#scrub-date").textContent = ""; } }

/* ---------- selection ---------- */
function select(runId, keepStock) {
  S.runId = runId; const r = run(); if (r) store.set("run", runId);
  setupFrames(r); runsTable(); signal(r); showAll();
  $("#chart-sub").textContent = r ? `${D.stocks[S.stock].name} · click a marker or a row to choose a decision · ${r.version} decision on ${r.decision_date} selected` : D.stocks[S.stock].name;
}
function chooseStock(t) {
  S.stock = t; store.set("stock", t); $("#stock").value = t;
  priceSeries.setData(series(t));
  const rs = stockRuns(); const pick = rs.filter(r => r.action === "BUY").at(-1) || rs.at(-1);
  select(pick ? pick.run_id : null);
}

/* ---------- improvement tab ---------- */
const avg = a => { const v = a.filter(x => x != null && !isNaN(x)); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };
function improvement() {
  const vs = D.versions.filter(v => D.runs.some(r => r.version === v));
  const byV = v => D.runs.filter(r => r.version === v && r.status === "scored");
  const setAvg = (v, set) => avg(byV(v).filter(r => r.eval_set === set).map(r => r.vs_hold));
  const vet = D.runs.filter(r => r.vetoed === "yes" && r.plan.ret != null), right = vet.filter(r => r.veto_right === "yes").length;
  const first = vs.find(v => setAvg(v, "practice") != null), last = [...vs].reverse().find(v => setAvg(v, "practice") != null);
  const tl = $("#imp-tiles"); tl.innerHTML = "";
  const tile = (l, b, n) => tl.append(h("div", { class: "tile" }, h("span", { class: "lbl", text: l }), h("span", { class: "big", html: b }), h("span", { class: "note", text: n })));
  tile("Scored decisions", String(D.runs.filter(r => r.status === "scored").length), `${D.runs.filter(r => r.action === "BUY").length} trades across ${vs.length} prompt versions`);
  if (first && last) tile("Practice set, vs holding", `${pts(setAvg(first, "practice"))} → ${pts(setAvg(last, "practice"))}`, `${first} to ${last}, same 8 stocks`);
  const ex = vs.filter(v => setAvg(v, "exam") != null); if (ex.length) tile("Exam set, vs holding", ex.map(v => pts(setAvg(v, "exam"))).join(" → "), ex.join(" to ") + ", same 8 unseen stocks");
  tile("Vetoes that were right", `${right} of ${vet.length}`, "a veto is right when the blocked plan would have lost");

  const t = $("#ver-table"); t.innerHTML = "";
  t.append(h("thead", {}, h("tr", {}, ...["Version", "Runs", "Trades", "Won / lost", "Avg result", "Avg vs holding", "Practice vs hold", "Exam vs hold", "Vetoes right"]
    .map((x, i) => h("th", { class: i ? "n" : "", text: x })))));
  const tb = h("tbody"); vs.forEach(v => { const rs = byV(v), b = rs.filter(r => r.action === "BUY"), w = b.filter(r => r.ret > 0).length;
    const vv = rs.filter(r => r.vetoed === "yes" && r.plan.ret != null), vr = vv.filter(r => r.veto_right === "yes").length;
    const cell = (x, f = pts) => h("td", { class: "n " + sign(x), text: f(x) });
    tb.append(h("tr", {}, h("td", { class: "mono", text: v }), h("td", { class: "n", text: rs.length }), h("td", { class: "n", text: b.length }),
      h("td", { class: "n", text: `${w} / ${b.length - w}` }), cell(avg(rs.map(r => r.ret)), pct), cell(avg(rs.map(r => r.vs_hold))),
      cell(setAvg(v, "practice")), cell(setAvg(v, "exam")), h("td", { class: "n", text: vv.length ? `${vr} of ${vv.length}` : "–" }))); });
  t.append(tb);

  runningChart();
  const md = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const cl = $("#changelog"); cl.innerHTML = "";
  D.changelog.filter(c => /^v/.test(c.title)).reverse().forEach(c => { const [v, hash] = c.title.split(/\s+/); const out = []; let list = null, para = [];
    const flush = () => { if (para.length) { out.push(`<p style="margin:0">${md(para.join(" "))}</p>`); para = []; } };
    c.body.split("\n").forEach(l => { if (/^- /.test(l)) { flush(); if (!list) { list = []; out.push(list); } list.push(md(l.slice(2))); }
      else if (/^\s+\S/.test(l) && list) list[list.length - 1] += " " + md(l.trim()); else if (!l.trim()) { flush(); list = null; } else { list = null; para.push(l.trim()); } }); flush();
    cl.append(h("div", { class: "ver" }, h("div", {}, h("div", { class: "v", text: v }), h("div", { class: "h", text: hash || "" })),
      h("div", { class: "b", html: out.map(o => Array.isArray(o) ? `<ul>${o.map(i => `<li>${i}</li>`).join("")}</ul>` : o).join("") }))); });
}

function runningChart() {
  const box = $("#running"); box.innerHTML = "";
  const rs = D.runs.filter(r => r.status === "scored" && r.vs_hold != null); if (!rs.length) return;
  const W = Math.max(320, box.clientWidth || 520), H = 230, m = { l: 40, r: 10, t: 16, b: 26 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
  let s = 0; const run = rs.map((r, i) => (s += r.vs_hold) / (i + 1));
  const vals = [...rs.map(r => r.vs_hold), ...run]; const lo = Math.min(-5, ...vals), hi = Math.max(5, ...vals);
  const clampLo = Math.max(lo, -25), clampHi = Math.min(hi, 25); const x = i => m.l + (rs.length === 1 ? iw / 2 : iw * i / (rs.length - 1));
  const y = v => m.t + ih * (clampHi - Math.max(clampLo, Math.min(clampHi, v))) / (clampHi - clampLo);
  const NS = "http://www.w3.org/2000/svg", el = (tag, a) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); return e; };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Running average of the team minus holding" });
  [clampLo, clampLo / 2, 0, clampHi / 2, clampHi].forEach(t => { svg.append(el("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: t === 0 ? "#6f7886" : C.grid }));
    const tx = el("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end" }); tx.textContent = (t > 0 ? "+" : "") + Math.round(t); svg.append(tx); });
  let prev = null, lastLabel = -99; rs.forEach((r, i) => { if (r.version !== prev) { svg.append(el("line", { x1: x(i), x2: x(i), y1: m.t, y2: H - m.b, stroke: C.line, "stroke-dasharray": "3 3" }));
      if (x(i) - lastLabel > 30) { const tx = el("text", { x: x(i) + 3, y: H - 8 }); tx.textContent = r.version; svg.append(tx); lastLabel = x(i); } prev = r.version; }
    const c = el("circle", { cx: x(i), cy: y(r.vs_hold), r: 3.5, fill: r.action === "BUY" ? C.blue : C.ref, opacity: .55 });
    const tt = el("title", {}); tt.textContent = `${r.company} ${r.decision_date} (${r.version}): ${r.action === "BUY" ? "BUY" : "skip"}, vs holding ${pts(r.vs_hold)}`; c.append(tt); svg.append(c); });
  svg.append(el("path", { d: run.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" "), fill: "none", stroke: C.up, "stroke-width": 2 }));
  box.append(svg);
  box.append(h("div", { class: "legend" }, h("span", {}, h("i", { class: "sw", style: `background:${C.up}` }), "Running average"),
    h("span", {}, h("i", { class: "dot", style: `background:${C.blue}` }), "Trade"), h("span", {}, h("i", { class: "dot" }), "Skip")));
}

/* ---------- paper trades tab ---------- */
function paper() {
  const open = D.runs.filter(r => r.status === "pending"); $("#paper-count").textContent = open.length ? String(open.length) : "";
  const box = $("#paper"); box.innerHTML = "";
  if (!open.length) { box.append(h("p", { class: "empty", text: "No open paper trades yet. Start one with the steps below; it appears here after it is scored." })); return; }
  const t = h("table"); t.append(h("thead", {}, h("tr", {}, ...["Stock", "Decided", "Decision", "Entry", "Stop / target", `Marked ${open[0].mark_date || ""}`].map((x, i) => h("th", { class: i > 2 ? "n" : "", text: x })))));
  const tb = h("tbody"); open.forEach(r => tb.append(h("tr", {}, h("td", { text: `${r.company} (${r.ticker})` }), h("td", { class: "mono", text: r.decision_date }),
    h("td", { text: r.action === "BUY" ? `BUY ${r.size}%` : "skip" }), h("td", { class: "n", text: r.entry_px ? `${usd(r.entry_px)} · ${r.entry_date}` : "next close" }),
    h("td", { class: "n", text: r.action === "BUY" ? `${usd(r.stop_px)} / ${usd(r.target_px)}` : "–" }), h("td", { class: "n " + sign(r.mark_pct), text: pct(r.mark_pct) }))));
  t.append(tb); box.append(h("div", { class: "tablewrap" }, t));
}

/* ---------- tabs and boot ---------- */
function tab(name) {
  ["trades", "improve", "paper"].forEach(n => { $("#tab-" + n).setAttribute("aria-selected", String(n === name)); $("#view-" + n).hidden = n !== name; });
  store.set("tab", name); if (name === "improve") runningChart();
}

async function boot() {
  try { const res = await fetch("data.json", { cache: "no-cache" }); if (!res.ok) throw new Error(res.status); D = await res.json(); }
  catch (e) { const s = $("#status"); s.hidden = false; s.textContent = "Couldn't load data.json. Run python agent_dashboard.py, then open this page through run_dashboard.bat (a local server), not as a file."; return; }
  if (!window.LightweightCharts) { const s = $("#status"); s.hidden = false; s.textContent = "The chart library didn't load (it needs an internet connection the first time)."; return; }
  FEE = D.config.fee / 100; SLIP = D.config.slippage / 100;
  $("#asof").textContent = `Prices through ${D.asof} · built ${D.generated.replace("T", " ")}`;
  document.querySelectorAll(".asof-inline").forEach(e => e.textContent = D.asof);
  $("#cost").textContent = `${D.config.fee}% fee and ${D.config.slippage}% slippage on each side`;
  const sel = $("#stock"); Object.entries(D.stocks).sort((a, b) => a[1].name.localeCompare(b[1].name)).forEach(([t, st]) =>
    sel.append(h("option", { value: t, text: `${st.name} (${t}) · ${D.runs.filter(r => r.ticker === t).length}` })));
  const vsel = $("#version"); vsel.append(h("option", { value: "all", text: "All versions" }));
  D.versions.filter(v => D.runs.some(r => r.version === v)).forEach(v => vsel.append(h("option", { value: v, text: v })));
  makeCharts();
  sel.addEventListener("change", () => chooseStock(sel.value));
  vsel.addEventListener("change", () => { S.version = vsel.value; chooseStock(S.stock); });
  $("#play").addEventListener("click", () => S.playing ? stop() : play());
  $("#reset").addEventListener("click", showAll);
  $("#scrub").addEventListener("input", e => { stop(); frame(+e.target.value); });
  ["trades", "improve", "paper"].forEach(n => $("#tab-" + n).addEventListener("click", () => tab(n)));
  improvement(); paper();
  const saved = store.get("stock"); const first = D.stocks[saved] ? saved : (D.stocks["2454.TW"] ? "2454.TW" : Object.keys(D.stocks)[0]);
  chooseStock(first); const sr = store.get("run"); if (sr && D.runs.some(r => r.run_id === sr && r.ticker === first)) select(sr);
  tab(store.get("tab") || "trades");
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (!$("#view-improve").hidden) runningChart(); }, 150); });
}
boot();
