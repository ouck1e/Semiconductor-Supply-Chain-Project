# Semiconductor Supply Chain Project

Independent research on the global semiconductor supply chain (chemical engineering, electrical engineering,
machine learning, finance, mineral economics), published as a live website:
https://ouck1e.github.io/Semiconductor-Supply-Chain-Project/

The owner is a student learning as he builds. Explain changes in plain language, and say why, not just what.

## Where things are

- **The website is `docs/`.** `docs/index.html` is the one live page: the 3D supply-chain globe (three.js r128)
  on top, the chip stock tracker below. Its code is split into `docs/styles.css`, `docs/globe.js` and
  `docs/tracker.js`. `docs/config.js` holds site settings (`liveQuotesUrl`).
  Edit only `docs/` for website work. `globe/` and any other copies of the globe or tracker are old drafts.
- **Site data is generated.** `docs/data/*.json` and `docs/data/prices/*.json` are written by `build_site_data.py`
  from the research outputs. Do not edit them by hand. The risk layer is also injected into `docs/globe.js`
  between the `/*RISK_JSON*/` and `/*END_RISK*/` markers; keep those markers.
- **Research pipeline (Python):**
  - `fetch_trade.py`, `fetch_trade_extra.py`: UN Comtrade imports to `data/raw/` and `data/raw_mirror/`
  - `fetch_gpr.py`: Geopolitical Risk Index
  - `fetch_prices.py`: daily prices for 26 companies and 8 benchmarks to `data/market/market.db`
  - `news_collector.py`, `news_gazetteer.py`, `news_sources.json`: news feeds, tagging and alerts
  - `phase2_event_study.py`, `phase3_models.py`, `phase4_wafer_usage.py`, `phase5_cost_dcf.py`,
    `phase8_market_models.py`, `exposure_model.py`: the models (README.md explains each)
  - `data/reference/`: hand-sourced inputs (fab capacity by country, foundry mix, trade overrides). Keep the
    source column filled in for every row.
- **Scheduled jobs (`.github/workflows/`):** news hourly, prices weekdays after the US close, trade data and risk
  on Mondays. Each runs a script, then `build_site_data.py`, then `.github/actions/commit`, then `deploy.yml`
  (GitHub Pages). Their commits land on `main` every hour.
- `worker/`: an optional Cloudflare Worker that relays live Finnhub quotes so the API key stays private.
- `.bat` files: launchers for running scripts on Windows by double-clicking.

## Rules

- **Never commit or print secrets.** `comtrade_key.txt` stays local and git-ignored. On GitHub the key is a
  repository secret (`COMTRADE_KEY`, or `COMTRADEKEY`). The Finnhub key lives only in the Cloudflare Worker.
- **Pull before working.** The scheduled jobs commit hourly, so run `git pull` before changing anything.
- Keep `docs/` a static site: no build step and no server. Libraries load from cdnjs with pinned versions.
  Data loads with `fetch()` from relative paths (`data/...`).
- Don't break the data contract between `build_site_data.py` and the page. If you change a JSON shape,
  change both in the same commit.
- Weekly Comtrade runs have a quota of about 500 calls a day; fetch only missing or recent years
  (the default). Use `--full` only when asked.
- Any script that writes files outside `docs/` (charts in `figures/`, for example) is fine. The commit step
  autostashes them.

## Design

The page is deliberately dark:

- **Palette:** Midnight Slate, with space `#0B0D10` and deep `#1A1F26`. Up `#3ccf95`, down `#f0566f`,
  accent blue `#3b7bfa`, event gold `#ffd36b`.
- **Fonts:** Chakra Petch for display headings, IBM Plex Mono for data, IBM Plex Sans for tracker text.
- **Tracker styles** are scoped under `#tracker` with `tk-` ids, so they don't clash with the globe's styles.
- **Layout:** it must work at phone width (about 400px) with no sideways scrolling.

## Checking your work

- Preview the site: `python -m http.server -d docs 8000`, then open http://localhost:8000. Check the globe, the
  scroll down to the tracker, a stock change, the event flags and the browser console for errors.
- Rebuild site data from local outputs: `python build_site_data.py all`.
- After pushing, check the Actions tab and the live site.

Research on how markets react to supply shocks, not investment advice. Keep that line on the site.
