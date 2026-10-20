# Semiconductor Supply Chain Risk Engine

Independent research on the global semiconductor supply chain (chemical engineering, electrical engineering,
machine learning, finance and mineral economics), published as a live website: a 3D supply-chain globe with
hourly news and risk alerts, and a stock tracker for 26 chip supply-chain companies.

**Website:** https://OWNER.github.io/REPO/ (GitHub Pages, served from `docs/`)

## How the website stays up to date

Scheduled GitHub Actions jobs run the research scripts on GitHub's servers and commit fresh data to `docs/data/`.
Each job then redeploys the site. Your PC is not needed.

| Job | When (UTC) | What it runs | Updates |
|---|---|---|---|
| `News (hourly)` | every hour at :17 | `news_collector.py` | `docs/data/news.json`: about 40 feeds, tagged by country, topic and input, with alerts |
| `Stock prices (daily)` | weekdays 22:23 | `fetch_prices.py` | `docs/data/prices/*.json`, `meta.json` (incl. each stock's reaction to the four shocks), `fx.json` |
| `Trade data and risk (weekly)` | Mondays 09:41 | `fetch_trade.py`, `fetch_trade_extra.py`, `fetch_gpr.py`, `phase3_models.py` | `docs/data/risk.json` and the risk layer in `docs/globe.js` |
| `Deploy website` | after each job, and on any push to `docs/` | | GitHub Pages |

`docs/data/status.json` records when each part last updated; the page shows it under the tracker title.
`build_site_data.py` turns the research outputs into the website's data files.

GitHub runs scheduled jobs within about 5 to 30 minutes of the set time, and stops scheduled jobs in a public
repository after 60 days without commits. The hourly news commits keep the repository active.

### Where data lives
- **Committed:** code, `docs/` (the website and its data), `data/reference/`, `data/external/gpr_monthly.csv`, figures.
- **Committed and updated weekly:** the raw UN Comtrade files (`data/raw/`, `data/raw_mirror/`), so each weekly run
  only asks Comtrade for missing years plus the latest two (countries revise recent months).
- **Not committed:** the news archive (`data/news/news.db`). It is kept in the GitHub Actions cache between hourly runs;
  if the cache is cleared, the next run starts a fresh 30-day archive.
- **Secrets:** the Comtrade key is a repository secret, `COMTRADE_KEY`. It is never in the code or on the website.

### Put it on GitHub (one time, about 10 minutes)
0. Double-click **install_github_jobs.bat** in this folder. It moves the scheduled-job files from `_github/` into
   `.github/` (Claude could not write that folder remotely). Skip this if `.github/workflows/` already exists.
1. Install **GitHub Desktop** (desktop.github.com) and sign in with your GitHub account.
2. **File > Add local repository**, choose this folder (`semiconductor-risk-engine`). When it says the folder is not a
   repository yet, click **create a repository**, then **Create repository**. Check that `comtrade_key.txt` is NOT in
   the list of changes (`.gitignore` excludes it).
3. **Publish repository**. Untick **Keep this code private** (free GitHub Pages needs a public repository).
   Your key and the news archive are never uploaded.
4. On github.com, open the repository: **Settings > Secrets and variables > Actions > New repository secret**,
   name `COMTRADE_KEY`, paste the key from `comtrade_key.txt`.
5. **Settings > Pages > Build and deployment > Source: GitHub Actions.**
6. **Actions** tab: run **News (hourly)**, **Stock prices (daily)** and **Trade data and risk (weekly)** once each
   (**Run workflow**). The site appears at `https://<your-username>.github.io/semiconductor-risk-engine/`.

### One-time setup (already covered in steps 4–6 above)
1. **Settings > Secrets and variables > Actions > New repository secret**: name `COMTRADE_KEY`, value = your key.
2. **Settings > Pages > Build and deployment > Source: GitHub Actions.**
3. **Actions tab**: open each workflow and click **Run workflow** once (start with `Trade data and risk`).

### Live stock prices (optional)
The tracker shows daily closes. To add live prices for US-listed stocks (and TSMC, UMC and ASML through their
New York listings), deploy the small relay in `worker/` so your API key stays private:
1. Get a free API key at finnhub.io (free plan: personal use, 60 calls a minute).
2. Create a free Cloudflare account, then **Workers & Pages > Create > Worker**, paste `worker/worker.js`, deploy.
3. In the worker's **Settings > Variables**, add a secret `FINNHUB_KEY`, and set `ALLOWED_ORIGIN` to your site
   (for example `https://OWNER.github.io`).
4. Put the worker's URL in `docs/config.js` (`liveQuotesUrl`) and commit. The tracker then shows a live price
   line for the selected stock, refreshed every 20 seconds.

Samsung, SK hynix, SMIC, MediaTek and the Japanese and Australian listings have no free live feed; the tracker
shows their latest daily close. Check the data provider's terms before showing live prices on a public site.

### Running things on your PC
Everything still runs locally from the `.bat` launchers, as before. Put your key in `comtrade_key.txt` (ignored by git).
To preview the website locally, run `python -m http.server -d docs 8000` and open http://localhost:8000.

---

# Semiconductor Supply Chain Risk Engine

Phase 1: monthly UN Comtrade import data for helium (HS 2804.29), gallium (HS 8112.92)
and hydrogen fluoride (HS 2811.11) into South Korea, Japan, the US and China, since 2015.

## Setup (once)
1. Open `comtrade_key.txt` in Notepad, replace `paste_your_key_here` with your Comtrade primary key, and save.
   Keep it private; it is excluded from git.
2. `pip install -r requirements.txt`

## Run
`python fetch_trade.py`  (about 150 API calls, roughly 5 minutes)

## Output
- `data/raw/` one CSV per material and importer, as Comtrade returns it
- `data/processed/imports_monthly.csv` cleaned rows: date, importer, supplier, kg, US$, US$/kg
- `data/processed/supplier_concentration.csv` monthly HHI and top supplier per importer
- `figures/korea_helium_by_supplier.png`

## Known data limits
- Taiwan does not report to Comtrade; rebuild its imports from partners' exports to "Other Asia, nes" (490).
- HS 2804.29 mixes helium with neon, krypton and xenon; use US$/kg to tell them apart.
- HS 8112.92 mixes gallium with other minor metals.
- The latest 2–3 months are often missing because countries report with a lag.

## Phase 2: event studies
`python phase2_event_study.py`  (no internet or API key needed; reads `data/raw/`)

- Splits HS 2804.29 into helium vs. other rare gases (mostly neon): helium = from a helium-producing
  country and under $300/kg; everything else = rare gas. Supplier first, so the rule is not circular in a price shock.
- Drops Comtrade-estimated weights and volumes; a price is shown only when reported quantities cover 60%+ of value.
- Compares the 12 months before and after each shock: HF 2019 (Korea), neon 2022 (Korea),
  gallium 2023 (Japan, US), helium 2026 (US, through Jul 2026).

Outputs: `data/processed/event_study_summary.csv`, `data/processed/imports_classified.csv`, `figures/event_*.png`.

## Phase 3: forecasting and exposure models
1. `python fetch_gpr.py` (or double-click `run_gpr.bat`) downloads the Geopolitical Risk Index to `data/external/`.
2. `python phase3_models.py` trains and tests both models (uses XGBoost if installed, else scikit-learn).
   Set `HORIZON=6` in the environment to test a 6-month window instead of 3.

All tests are walk-forward (2019–2026): each test year trains only on months fully known before it.

**Model A, 3-month price forecast.** No model beats "price stays the same" by a useful margin (best blend:
1.5% lower error; gets the direction of moves over 5% right 58% of the time). Adding the risk index made it
slightly worse. Import prices for these inputs behave close to a random walk at this horizon, so the cost
model should use scenario shocks from the phase 2 event studies rather than point forecasts.

**Model B, supplier-drop exposure.** Predicts a >50% drop in physical volume (kg; US$ where weights are
unreported) from a key supplier (10%+ share, $1M+/yr) within 3 months. Volume, not value: in a supply shock
prices jump, so value can rise while shipments fall (Korea's neon from Ukraine in 2022).
- Trade data only: ROC AUC 0.76 (boosted trees), 0.73 (logistic); 64-66% of its top-10% riskiest cases dropped vs. a 21% base rate.
- Adding the Geopolitical Risk Index (global + supplier-country, Gulf states via Saudi Arabia): no gain
  (AUC 0.76 / 0.71). Same result at a 6-month horizon.
- Why: crises trigger stockpiling first (US helium from Qatar surged Jan–Mar 2026; Korea's Ukrainian neon
  peaked in May 2022), and with only a handful of shocks the model cannot learn how risk turns into shortage.
  Better use for the index: an alert on the dashboard (supplier-country risk spiking while that supplier holds a large share).

Outputs: `data/processed/model_a_price_forecast_results.csv`, `model_b_exposure_results.csv`, `model_b_metrics.csv`
(with vs. without GPR), `exposure_scores_latest.csv` (feeds the globe), `figures/model_a_skill.png`, `figures/model_b_cases.png`.

## Phase 4: per-wafer usage
`python phase4_wafer_usage.py` (or double-click `run_phase4_5.bat`, which runs phases 4 and 5; no internet needed)

Low / central / high amounts of helium, neon, HF and gallium per wafer, today's unit prices from your
Comtrade data, $ per wafer, and days of on-site inventory. Every number has its source in a comment.
- HF is now in kg **as traded** (mixed concentrations, the Comtrade unit). Cross-check against Korea's imports:
  all HF imports / Korea's ~28M wafers = 3.8 kg per wafer (upper bound); Japan's pre-2019 HF to Korea = 1.2 kg
  (central). The earlier 150 g of pure HF (Williams 2002, ~0.3 kg as traded) becomes the low case.
- At central amounts and 2025 prices the three silicon-fab inputs cost about $10.50 per wafer:
  helium $8.13, HF $2.06, neon $0.32.

Outputs: `data/processed/per_wafer_usage.csv`, `data/processed/hf_crosscheck.csv`.

## Phase 5: wafer cost model and fab DCF
`python phase5_cost_dcf.py` (set `N_RUNS` to change the 10,000 Monte Carlo runs)

Reference fab: 7 nm-class, 50,000 wafers/month, $9,346 per wafer, $8.6B capex (CSET 2020 prices and capital
intensity), 53% gross margin, 5-year depreciation, 9% discount rate, 10 years.
- Neon-sized shock (price x3.75 for a year, no volume loss): $1-22 extra per wafer, at most 0.24% of its price.
- HF-sized shock (lose 25% of supply, replacement takes ~90 days): $33-67 per wafer averaged over a year,
  because lost output after inventory runs out costs ~$12M a day in margin. Lost output dominates price.
- Monte Carlo (each input: 10% chance of a shock a year, half of each kind): median loss 0.22% of the fab's
  $12.7B NPV; 1 run in 20 loses more than 0.72%, 1 in 100 more than 0.98%.

Outputs: `data/processed/phase5_scenarios.csv`, `phase5_dcf_montecarlo.csv`, `phase5_summary.csv`,
`figures/phase5_cost_per_wafer.png`, `figures/phase5_npv_distribution.png`.

## News layer (for the globe and the app)
`python news_collector.py` (or double-click `run_news.bat`; needs internet, no API keys). Run it daily; each run
adds to the archive and refreshes the 30-day feed.

Collects semiconductor and supply-chain stories from trade press (Semiconductor Engineering, EE Times, TrendForce,
Tom's Hardware...), regional outlets (Taipei Times, Korea Herald, Nikkei Asia, SCMP), think tanks and economic
forums (CSIS, PIIE, WEF, IMF), GDELT (worldwide, 65 languages), Google News in 10 regional editions and local
languages, Hacker News and Reddit. Only headline, link, date and a short summary are kept.

Each story is tagged with the countries it names (headline counts most), a primary country and region, topics
(export controls, tariffs, critical materials, fabs, AI demand, equipment, markets, policy, disruption) and the
tracked inputs it mentions (helium, neon, HF, gallium). `alert` = a disruption or export-control story about a
tracked input or critical material; these feed the globe's risk monitor.
- Sources: `news_sources.json` (add, remove or switch off any feed; failed feeds are listed in `news_log.txt`)
- Places, companies, topics: `news_gazetteer.py`

Outputs: `data/news/news.db` (SQLite archive), `data/news/news_latest.json` (30 days, grouped by region and
country, for the globe), `data/news/news_by_region.csv`.

### News on the globe
`run_news.bat` now also runs `build_globe_news.py`, which writes the latest stories into `globe/orbit_globe.html`.
- Open `globe/orbit_globe.html` in a browser to see them right away (blue beacons = news by country,
  amber head = the country has an alert story; the Monitor panel's **News** tab lists and filters stories).
- The published Orbit Globe link shows the stories embedded at its last publish. To refresh it, either ask Claude to
  publish the new `globe/orbit_globe.html`, or click **Load news file** in the News tab and pick
  `data/news/news_latest.json` (that loads it in your browser only).

## Phase 8, step 1: stock prices
`python fetch_prices.py` (or double-click `run_prices.bat`; needs internet, installs `yfinance` on first run)

Daily prices since 2015 (same span as the Comtrade data) for 26 chip supply-chain companies on their home exchanges
(fabs, toolmakers, chip designers, gas and materials suppliers, rare earths), 8 benchmarks, 6 exchange rates and the
Fama-French daily factors (US and developed markets). `python fetch_prices.py --stats` rebuilds stats without downloading.

Outputs: `data/market/market.db` (SQLite: prices, fx, factors_us, factors_developed, universe),
`data/market/prices_adj_close.csv`, `data/market/stock_summary.csv` (US-dollar return, volatility, beta and
correlation to the SOXX chip ETF from weekly returns, max drawdown), `figures/stocks_by_group.png`,
`figures/stock_correlations.png`.

## Phase 8, step 2: stock models
`python phase8_market_models.py` (or `run_phase8_models.bat`; no internet needed, reads `data/market/market.db`)

1. Return decomposition: weekly Fama-French 5-factor regressions in US dollars (alpha, betas), plus up- and
   down-market betas to the SOXX chip ETF. `figures/m1_alpha.png`, `figures/m1_defensive.png`
2. What moves each stock: share of weekly variance from the world market, chip sector, home market and
   company-specific news. `figures/m2_drivers.png`
3. Clusters of stocks that move together after removing the world market. `figures/m3_clusters.png`
4. Event study of the four supply shocks with groups fixed in advance (expected losers and winners),
   market model with same-day and lagged MSCI World returns; robustness against the chip sector and each
   home market. `figures/m4_shocks.png`, `figures/m4_benchmarks.png`

Outputs: `data/market/model1_factor_regressions.csv`, `model2_variance_shares.csv`, `model3_clusters.csv`,
`model4_event_study.csv`, `model4_event_paths.csv`, `model4_benchmarks.csv`, `run_phase8_models_log.txt`.

## Phase 8, step 3: supply exposure by company
Data: `python fetch_trade_extra.py` (or `run_trade_extra.bat`; needs internet and `comtrade_key.txt`). Adds
monthly imports for Singapore, Germany, Ireland, Israel and Malaysia to `data/raw/`, and rebuilds Taiwan's
imports from every other country's exports to Taiwan in `data/raw_mirror/`. Files already complete are skipped,
so after a Comtrade quota stop just run it again.

Model: `python exposure_model.py` (or `run_exposure.bat`; no internet needed).

Exposure of company c to supplier s for input m in year y = sum over countries k of
(c's fab capacity share in k) x (k's import share from s, by value). Inputs:
- `data/reference/fab_footprint.csv`: capacity share by country for 8 chipmakers, with confidence and source.
- `data/reference/foundry_mix.csv`: chip designers (Nvidia, AMD, Qualcomm, MediaTek) inherit their foundries' footprint.
- `data/reference/trade_overrides.csv`: sourced shares where Comtrade misses a supplier (Taiwan's helium from Qatar,
  which does not report monthly).

Results are scaled to the capacity the trade data covers; `coverage` says how much that is (* in the heatmap = under half).

Outputs: `data/processed/exposure_matrix.csv` (every company x input x supplier x year),
`exposure_key_risks.csv`, `exposure_event_test.csv`, `exposure_pooled_test.csv`;
`figures/exposure_heatmap.png`, `figures/exposure_qatar_helium.png`, `figures/exposure_vs_reaction.png`.

Finding: exposure does not explain which stocks fell more in the HF 2019, neon 2022 or helium 2026 shocks
(pooled across shocks, home-market benchmark: p = 0.30). This fits phase 5: these inputs are a tiny share of
wafer cost, so markets treat the shocks as sector-wide news rather than company-specific risk.

Known gaps: US helium shares count imports only (the US produces most of its own); several capacity shares are
low-confidence estimates; Taiwan HF is missing until the mirror pull finishes (TSMC, UMC and the designers show *).

## AI agent team (simulation)
A six-role Claude team, following the structure of the SebAI "6 Claude Agents Simulation-First Trading Team Guide":
Researcher → News Analyst → Strategist → (Coder) → Risk Manager → Boss. Research and learning only: nothing places a
real order, and no broker is connected. The goal is to beat the phase 8 baseline below, and to record whether
the agents improve as their prompts change.

**1. The opponent.** `python phase8_baseline.py` (or `run_phase8_baseline.bat`) turns phase 8 into a fixed,
walk-forward, long-only rule: each month hold the top 5 companies by trailing 3-year Fama-French alpha t-stat (Model 1,
using only data available that day), and around Model 4's supply shocks swap expected losers for expected winners for
20 days. Fees and slippage included. Writes `data/agents/baseline_*.csv` and `figures/phase8_baseline.png`.
Result so far: it trails both SOXX and an equal-weight basket in the dev years (2018-2022) and the test years, so it is
a low bar. The scoreboard therefore also shows SOXX.

**2. A packet.** `python agent_packets.py --sample 1 --split dev` (or `run_agent_packet.bat`), or
`--ticker 2330.TW --date 2022-03-15`. Writes six ready-to-paste prompts to `data/agents/runs/<run_id>/` with fact sheets
built only from data up to the decision date: price indicators (Researcher), headlines and supply shocks (News Analyst),
phase 8 and exposure facts (Strategist). Past dates are **blind**: "Stock A", "Day 0", prices rebased to 100, no
headlines, because Claude remembers market history and would otherwise answer from memory. (The supply shocks are kept
and described without names or dates, which still hints at the period. That's a known limit.) The real stock and date go to
`data/agents/keys/`; never paste those into Claude.

**3. Run it by hand.** Follow `00_HOW_TO_RUN.txt` in the run folder: one Claude chat per agent, pasting each
handoff block into the next. The Boss ends with a `DECISION` block.

**4. Score it.** Save the Boss's reply as `boss.txt` in the run folder, then `python agent_score.py <run_id>`
(or `run_agent_score.bat`). It simulates the decision on the prices that followed (next-close entry, stop/target/max hold
on closes, fees and slippage), compares it with what the baseline earned on the same stock over the same days and with
SOXX. It also compares every run with simply buying the stock and holding it for the whole period (same costs, no
stop or target). That credits a NO TRADE before a fall as a "good skip" even when the baseline was out of the stock
too. If the Strategist's reply is saved in the run folder as `strategist.txt`, its `PLAN` block is played out as
well, approved or not. A veto counts as right when the vetoed plan would have lost money, so the record shows whether
the Risk Manager is helping. (Runs from before the PLAN block have a backfilled `strategist_plan.txt`.) It appends to:
- `data/agents/trade_log.csv`: one row per run, using the guide's trade-log columns plus the scores
- `data/agents/scoreboard.csv`: per prompt version and split: hit rate, average excess over the baseline, how often
  it beat the baseline, average result vs holding the stock, share of skips that were good skips, BUY plans proposed,
  vetoes, share of vetoes that were right, total return the vetoes saved, worst trade, longest losing streak
- `figures/agent_vs_phase8.png`: the running average excess over the baseline, run by run, coloured by prompt version

Every run records a `prompts_version` (a hash of `agents/prompts/`), so changing a prompt starts a new line on the
scoreboard. Honest-testing rules from the guide: tune prompts on **dev** dates only, score **test** dates rarely,
log rejected and NO TRADE runs too, and never describe simulated results as real ones. Forward runs (after the model's
training cutoff, `blind_before` in `agents/config.json`) are the cleanest test; score them later with
`python agent_score.py --update` once the prices exist.

**5. Compare prompt versions fairly.** `python agent_packets.py --make-set practice --sample 8 --split dev --seed 2026`
saves a fixed set of stock-dates (in `data/agents/keys/`, since it names the stocks); `--set practice` builds one packet
per stock-date for the current prompts, so every version is judged on the same stocks. An `exam` set from the test
years is scored only at the end of a round. `agents/CHANGELOG.md` records each prompt version, why it changed and what
the results showed. For automated runs, `agent_handoff.py <stage> <run_id>...` fills each prompt's handoff slots from
the saved replies. `python agent_report.py` writes `data/agents/run_summaries.csv` (every run's decision, outcome and
each agent's own summary of its reasoning), `report_data.json` and `figures/agent_training.png`.

**6. Dashboard and paper trading.** Double-click `run_dashboard.bat` (or run `python agent_dashboard.py`, then
`python -m http.server -d dashboard 8010` and open http://localhost:8010). The **Trades** tab draws each stock's daily
USD closes with the agents' buys, sells (stop / target / time) and skips, the stop and target levels, and a day-by-day
replay of any decision, with each agent's own reasoning beside it. **Improvement** shows results by prompt version, the
Risk Manager's veto record, a running average vs holding the stock, and the changelog. All of it is rebuilt from the
trade log, so every newly scored run adds to the record. **Paper trades** lists open forward decisions marked to the
latest close. To start one: `python agent_packets.py --ticker MU --date <latest trading day> --named`, run the six
agents, score it (it stays pending), and close it later with `python agent_score.py --update` once prices arrive.

**7. Daily paper trading (automatic).** `python agent_daily.py` runs the team through the Claude API instead of by
hand: for each stock on the watchlist in `agents/config.json` (`automation`: TSMC, Micron, ASML, MediaTek, Shin-Etsu)
it builds a named packet for the latest close, sends each agent its prompt, hands each reply on with
`agent_handoff.py`, and scores the Boss's decision, which stays pending until the prices close it. Runs are built
and scored exactly like manual ones; the `runner` column says which models ran (Opus 5.5 for every role, effort
medium). The Coder step is skipped, as in manual runs.
- **When:** every weekday, as extra steps of the "Stock prices (daily)" job, after the price update: close paper
  trades whose prices have arrived (`agent_score.py --update`), run the watchlist, rebuild the summaries, commit
  `data/agents`. These steps may fail without stopping the price update. `dashboard/data.json` is not committed (it is
  1.4 MB and rebuilt each time); `run_dashboard.bat` rebuilds it after a `git pull`. `run_paper_trading.bat` does a
  day by hand on your PC.
- **The key:** the script reads only the `ANTHROPIC_API_KEY` environment variable. On GitHub, add it under
  Settings > Secrets and variables > Actions as `ANTHROPIC_API_KEY`; on your PC, as a Windows user environment
  variable. Never put it in a file in this folder. Without it, the job skips the agents and does the rest.
- **Cost:** about $0.50 a run (5 calls), so about $50 a month for 5 stocks. Every call's tokens and dollars go to
  `data/agents/api_usage.csv`, and the script stops before the month's total could pass `monthly_budget_usd` ($60).
  Set the same limit in the Anthropic Console as a second guard.
- **Safeguards:** forward dates only (never before `blind_before`, so the practice and exam sets stay manual); a stock
  with an open BUY or a run for that date is skipped; an unreadable DECISION block gets one fix request, then the run
  is logged as failed rather than guessed. The script talks to the Claude API and nothing else: no broker, no orders.
- **To stop it:** delete the `ANTHROPIC_API_KEY` secret, or empty the watchlist.

**8. Time-span simulation.** `agent_span.py` lets the team trade one stock through a period you choose, so you can
watch it on candles. While it holds nothing, the full team makes a decision every 5 trading days (`--cadence`) and on
the day after each exit; while it holds, the trade runs on its own stop, target and time limit, scored exactly like
any other run. Each decision is an ordinary run (blind for past dates, `eval_set` = `sim:<id>`), so it also lands in
`trade_log.csv`. Before each decision the team is told what it did earlier in the span (prompt v6, see
`agents/CHANGELOG.md`).
- `python agent_span.py --ticker MU --start 2022-01-03 --end 2022-03-31` prints the decision days and a cost estimate
  and spends nothing.
- **Free, by hand:** add `--manual`. For each decision the script puts each agent's prompt on your clipboard (handoffs
  already filled in); paste it into a new Claude chat, click Copy under the reply, press Enter. It checks each copy
  (not the prompt again, a handoff block present, a readable DECISION block from the Boss) and scores the decision
  itself. Type `q` to stop; `python agent_span.py --resume <sim_id>` carries on from the same agent. About five pastes
  a decision, so a three-month span is roughly an evening. Turn web search off in those chats so blind runs stay blind.
- **Paid, automatic:** add `--yes` to run it through the Claude API (needs `ANTHROPIC_API_KEY`; about $1 a decision, and
  it stops at `monthly_budget_usd`). `--resume <sim_id>` continues an interrupted run. `--demo` runs a simple
  pullback rule instead of the agents, free, labelled DEMO and kept out of the trade log.
- The span needs enough later prices to close the last possible trade; the script says the latest end date allowed.
  Spans in the test years (2023 on) are fine to watch but shouldn't be used to tune prompts.
- Results go to `data/agents/sims/<sim_id>/sim.json`. `run_span.bat` asks for the stock and dates (or a sim id to continue), shows the estimate, offers hand / API / demo,
  runs, and rebuilds the dashboard, whose **Simulations** tab replays the span day by day: candles and volume, buy and
  sell markers, the holding period shaded, the agents' state and reasons, what they remembered, and team vs holding.
- Candles need open, high and low prices, which `fetch_prices.py` now stores (`adj_open`, `adj_high`, `adj_low`).

Settings: `agents/config.json` (portfolio, position and stop limits, fees, slippage, splits). Tests:
`python -m unittest discover tests`.
