/* Simulations tab: candles for a time span, the team's weekly checks, trades, and what the agents saw and said.
   Uses the helpers and data defined in dashboard.js (h, pct, pts, usd, sign, C, D, store). Simulation only. */
"use strict";

const SIM = { id: null, idx: 0, frames: [], playing: false, timer: null };
let candleChart, candleSeries, volSeries, bandSeries, simEqChart, simEqTeam, simEqHold, simLines = [];

const simNow = () => D.sims.find(s => s.sim_id === SIM.id);
const shortSetup = s => (s || "").replace(/^demo rule: /, "").slice(0, 28);

function simCharts() {
  const base = { autoSize: true, layout: { background: { type: "solid", color: "transparent" }, textColor: C.ink2, fontFamily: "IBM Plex Mono, monospace", fontSize: 11 },
    grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } }, rightPriceScale: { borderColor: C.line }, timeScale: { borderColor: C.line }, crosshair: { mode: 0 } };
  candleChart = LightweightCharts.createChart(document.querySelector("#candle-chart"), base);
  // holding periods: a faint full-height band on its own hidden scale, drawn first so candles sit on top
  bandSeries = candleChart.addHistogramSeries({ priceScaleId: "band", color: "rgba(59,123,250,0.16)", priceLineVisible: false, lastValueVisible: false });
  candleChart.priceScale("band").applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
  volSeries = candleChart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false });
  candleChart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });
  candleSeries = candleChart.addCandlestickSeries({ upColor: C.up, downColor: C.down, wickUpColor: C.up, wickDownColor: C.down, borderVisible: false,
    priceFormat: { type: "price", precision: 2, minMove: 0.01 } });
  simEqChart = LightweightCharts.createChart(document.querySelector("#sim-equity"), { ...base, handleScroll: false, handleScale: false });
  simEqHold = simEqChart.addLineSeries({ color: C.ref, lineWidth: 2, priceLineVisible: false });
  simEqTeam = simEqChart.addLineSeries({ color: C.blue, lineWidth: 2, priceLineVisible: false });
}

const trades = s => s.decisions.filter(d => d.action === "BUY" && d.entry_date);
// held on `date`: from the entry close up to the exit close. `closedOnExit` treats the exit day as already sold.
const openTradeOn = (s, date, closedOnExit = false) => trades(s).find(d => d.entry_date <= date &&
  (!d.exit_date || (closedOnExit ? date < d.exit_date : date <= d.exit_date)));

function simMarkers(s, upTo) {
  const m = [];
  s.decisions.forEach(d => {
    if (upTo && d.date > upTo) return;
    if (d.action === "BUY") {
      m.push({ time: d.date, position: "aboveBar", shape: "circle", color: C.blue, size: 0.8, text: "decide" });
      if (d.entry_date && (!upTo || d.entry_date <= upTo)) m.push({ time: d.entry_date, position: "belowBar", shape: "arrowUp", color: C.up, text: `BUY · ${shortSetup(d.setup)}` });
      if (d.exit_date && (!upTo || d.exit_date <= upTo)) m.push({ time: d.exit_date, position: "aboveBar", shape: "arrowDown", color: C.down, text: `SELL · ${d.exit_reason} ${pct(d.ret, 1)}` });
    } else m.push({ time: d.date, position: "aboveBar", shape: "circle", color: C.ref, size: 0.6, text: "" });
  });
  return m.sort((a, b) => a.time.localeCompare(b.time));
}

function simLevels(s, date) {
  simLines.forEach(l => candleSeries.removePriceLine(l)); simLines = [];
  const t = openTradeOn(s, date, true); if (!t || !t.entry_px) return;
  const line = (p, c, title) => simLines.push(candleSeries.createPriceLine({ price: p, color: c, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }));
  line(t.entry_px * (1 + t.target / 100), C.up, "target"); line(t.entry_px * (1 - t.stop / 100), C.down, "stop"); line(t.entry_px, C.blue, "entry");
}

function simDraw(s, upTo) {
  const c = s.candles.filter(k => !upTo || k.time <= upTo);
  candleSeries.setData(c.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
  volSeries.setData(c.filter(k => k.volume != null).map(k => ({ time: k.time, value: k.volume, color: k.close >= k.open ? "rgba(60,207,149,0.35)" : "rgba(240,86,111,0.35)" })));
  bandSeries.setData(c.map(k => ({ time: k.time, value: openTradeOn(s, k.time) ? 1 : 0 })));
  candleSeries.setMarkers(simMarkers(s, upTo)); simLevels(s, upTo || s.curve.at(-1).date);
  const cv = s.curve.filter(p => !upTo || p.date <= upTo);
  simEqTeam.setData(cv.map(p => ({ time: p.date, value: p.strategy }))); simEqHold.setData(cv.map(p => ({ time: p.date, value: p.hold })));
  simEqChart.timeScale().fitContent();
}

function simTiles(s, date) {
  const p = s.curve.filter(x => x.date <= date).at(-1) || s.curve[0];
  const set = (id, v, note, cls = "") => { const e = document.querySelector(id); e.textContent = v; e.className = "big " + cls; document.querySelector(id + "-note").textContent = note; };
  const strat = p.strategy - 100, hold = p.hold - 100;
  set("#s-strat", pct(strat), `${s.start} to ${p.date}`, sign(strat));
  set("#s-hold", pct(hold), "all in from the first close", sign(hold));
  set("#s-vs", pts(strat - hold), "points", sign(strat - hold));
  const done = trades(s).filter(d => d.exit_date && d.exit_date <= date), won = done.filter(d => d.ret > 0).length;
  set("#s-trades", String(done.length), `${won} won, ${done.length - won} lost · ${s.decisions.filter(d => d.date <= date).length} checks`);
  set("#s-port", usd(p.portfolio, 0), `${pct((p.portfolio / D.config.portfolio - 1) * 100)} with the agents' position sizes`, sign(p.portfolio - D.config.portfolio));
}

function simDesk(s, date) {
  const box = document.querySelector("#desk-state"), rows = document.querySelector("#desk-rows"), why = document.querySelector("#desk-why");
  box.innerHTML = ""; rows.innerHTML = ""; why.innerHTML = "";
  const t = openTradeOn(s, date, true) || s.decisions.find(d => d.action === "BUY" && d.date <= date && d.entry_date > date);
  const last = s.decisions.filter(d => d.date <= date).at(-1), next = s.decisions.find(d => d.date > date);
  const k = s.candles.find(c => c.time === date) || s.candles.filter(c => c.time <= date).at(-1);
  if (t && date >= t.entry_date) {
    const held = s.curve.filter(p => p.date >= t.entry_date && p.date <= date).length - 1, un = (k.close / t.entry_px - 1) * 100;
    box.append(h("div", { class: "head hold" }, h("b", { text: "HOLDING" }), h("span", { text: shortSetup(t.setup) || "position open" })),
      h("p", { text: `Bought ${t.size}% at ${usd(t.entry_px)}. Day ${held} of at most ${t.hold_days}. Sells at ${usd(t.entry_px * (1 - t.stop / 100))} (stop) or ${usd(t.entry_px * (1 + t.target / 100))} (target).` }));
    rows.append(h("dt", { text: "Open result" }), h("dd", { class: sign(un), text: pct(un) }));
  } else {
    box.append(h("div", { class: "head skip" }, h("b", { text: "FLAT" }), h("span", { text: next ? `next check ${next.date}` : "span finished" })),
      h("p", { text: t ? `Decided to buy; fills at the close on ${t.entry_date}.` : "No position. While flat the team checks once a week." }));
  }
  const add = (a, b, cls = "") => rows.append(h("dt", { text: a }), h("dd", { class: cls, text: b }));
  add("Date", date); add("Close", usd(k?.close));
  if (last) {
    add("Last check", `${last.date}: ${last.action === "BUY" ? "BUY" : "no trade"}`);
    if (last.action === "BUY") add("Plan", `${last.size}% · −${last.stop}% / +${last.target}% · ${last.hold_days}d`);
    [["Strategist", last.strategist], ["Risk Manager", last.risk_manager], ["Boss", last.boss]].forEach(([a, b]) => b && why.append(h("div", {}, h("h3", { text: a }), h("p", { text: b }))));
    if (!why.children.length) why.append(h("p", { class: "muted", text: "No reasoning saved for this check." }));
    document.querySelector("#desk-memory").textContent = last.memory;
  } else { why.append(h("p", { class: "muted", text: "The first check hasn't happened yet." })); document.querySelector("#desk-memory").textContent = ""; }
}

function simEvents(s) {
  const ev = [];
  s.decisions.forEach(d => {
    if (d.action === "BUY") {
      ev.push([d.date, "PLAN", `Decided BUY ${d.size}% (${shortSetup(d.setup)}), stop −${d.stop}%, target +${d.target}%`]);
      if (d.entry_date) ev.push([d.entry_date, "BUY", `Bought at ${usd(d.entry_px)}`]);
      if (d.exit_date) ev.push([d.exit_date, "SELL", `Sold at ${usd(d.exit_px)}: ${d.exit_reason}, ${pct(d.ret)}`]);
    } else ev.push([d.date, "SKIP", "Weekly check: no trade"]);
  });
  return ev.sort((a, b) => a[0].localeCompare(b[0]));
}

function simLog(s, date) {
  const ol = document.querySelector("#sim-log"); ol.innerHTML = "";
  const ev = simEvents(s).filter(e => !date || e[0] <= date).reverse();
  if (!ev.length) ol.append(h("li", {}, h("time", { text: "" }), h("span", { class: "k INFO", text: "INFO" }), h("span", { text: "Nothing yet." })));
  ev.forEach(([d, k, t]) => ol.append(h("li", {}, h("time", { text: d }), h("span", { class: "k " + k, text: k }), h("span", { text: t }))));
}

function simTable(s) {
  const t = document.querySelector("#sim-decisions"); t.innerHTML = "";
  t.append(h("thead", {}, h("tr", {}, ...["Check", "Decision", "Strategy", "Entry", "Exit", "Result"].map((x, i) => h("th", { class: i > 2 ? "n" : "", text: x })))));
  const tb = h("tbody");
  s.decisions.forEach(d => { const tr = h("tr", { class: "run", tabindex: "0" },
      h("td", { class: "mono", text: d.date }), h("td", {}, h("span", { class: "tag" + (d.action === "BUY" ? " buy" : ""), text: d.action === "BUY" ? "BUY" : "no trade" })),
      h("td", { text: d.action === "BUY" ? shortSetup(d.setup) : "" }), h("td", { class: "n", text: d.entry_date ? `${usd(d.entry_px)} · ${d.entry_date}` : "" }),
      h("td", { class: "n", text: d.exit_date ? `${usd(d.exit_px)} · ${d.exit_reason}` : "" }), h("td", { class: "n " + sign(d.ret), text: d.action === "BUY" ? pct(d.ret) : "" }));
    const go = () => { simStop(); simFrame(Math.max(0, SIM.frames.indexOf(d.exit_date || d.date))); };
    tr.addEventListener("click", go); tr.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    tb.append(tr); });
  t.append(tb);
}

/* replay */
function simFrame(i) {
  const s = simNow(); if (!s) return; SIM.idx = i; const date = SIM.frames[i];
  simDraw(s, date); simTiles(s, date); simDesk(s, date); simLog(s, date);
  candleChart.timeScale().setVisibleRange({ from: s.candles[0].time, to: s.candles.at(-1).time });
  document.querySelector("#s-scrub").value = String(i); document.querySelector("#s-scrub-date").textContent = date;
}
function simPlay() {
  if (!SIM.frames.length) return; if (SIM.idx >= SIM.frames.length - 1) SIM.idx = 0;
  SIM.playing = true; document.querySelector("#s-play").textContent = "❚❚ Pause";
  const step = () => { simFrame(SIM.idx); if (SIM.idx >= SIM.frames.length - 1) { simStop(); return; } SIM.idx++; SIM.timer = setTimeout(step, +document.querySelector("#s-speed").value); };
  step();
}
function simStop() { clearTimeout(SIM.timer); SIM.playing = false; document.querySelector("#s-play").textContent = "▶ Play the span"; }

function chooseSim(id) {
  simStop(); SIM.id = id; store.set("sim", id); const s = simNow(); if (!s) return;
  document.querySelector("#sim").value = id; document.querySelector("#demo-note").hidden = !s.demo;
  document.querySelector("#sim-meta").textContent = `${s.version} · ${s.runner} · checks every ${s.cadence} trading days while flat · ${s.status}`;
  document.querySelector("#sim-sub").textContent = `${s.company} (${s.ticker}), ${s.start} to ${s.end} · daily candles in USD`;
  SIM.frames = s.curve.map(p => p.date); const sc = document.querySelector("#s-scrub"); sc.max = String(SIM.frames.length - 1);
  simTable(s); simFrame(SIM.frames.length - 1); document.querySelector("#s-scrub-date").textContent = "";
}

function simImprovementTable() {
  const t = document.querySelector("#sim-table"); t.innerHTML = "";
  t.append(h("thead", {}, h("tr", {}, ...["Simulation", "Version", "Span", "Checks", "Trades", "Won", "Team", "Holding", "vs holding", "Max drawdown"]
    .map((x, i) => h("th", { class: i > 2 ? "n" : "", text: x })))));
  const tb = h("tbody");
  if (!D.sims.length) tb.append(h("tr", {}, h("td", { colspan: "10", class: "empty", text: "No simulations yet." })));
  D.sims.forEach(s => tb.append(h("tr", {}, h("td", { text: `${s.company}${s.demo ? " (demo)" : ""}` }), h("td", { class: "mono", text: s.version }),
    h("td", { class: "mono", text: `${s.start} → ${s.end}` }), h("td", { class: "n", text: s.stats.decisions }), h("td", { class: "n", text: s.stats.trades }),
    h("td", { class: "n", text: s.stats.won }), h("td", { class: "n " + sign(s.stats.strategy_pct), text: pct(s.stats.strategy_pct) }),
    h("td", { class: "n", text: pct(s.stats.hold_pct) }), h("td", { class: "n " + sign(s.stats.vs_hold), text: pts(s.stats.vs_hold) }),
    h("td", { class: "n", text: pct(s.stats.max_drawdown_pct) }))));
  t.append(tb);
}

function simsInit() {
  D.sims = D.sims || [];
  document.querySelector("#sim-count").textContent = D.sims.length ? String(D.sims.length) : "";
  simImprovementTable();
  const empty = !D.sims.length; document.querySelector("#sim-empty").hidden = !empty; document.querySelector("#sim-body").hidden = empty;
  if (empty) return;
  simCharts();
  const sel = document.querySelector("#sim");
  D.sims.forEach(s => sel.append(h("option", { value: s.sim_id, text: `${s.company} · ${s.start} → ${s.end} · ${s.version}${s.demo ? " · DEMO" : ""}` })));
  sel.addEventListener("change", () => chooseSim(sel.value));
  document.querySelector("#s-play").addEventListener("click", () => SIM.playing ? simStop() : simPlay());
  document.querySelector("#s-reset").addEventListener("click", () => { simStop(); simFrame(SIM.frames.length - 1); document.querySelector("#s-scrub-date").textContent = ""; });
  document.querySelector("#s-scrub").addEventListener("input", e => { simStop(); simFrame(+e.target.value); });
  const saved = store.get("sim"); chooseSim(D.sims.some(s => s.sim_id === saved) ? saved : D.sims.at(-1).sim_id);
}
