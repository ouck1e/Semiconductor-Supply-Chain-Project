"""
Shared code for the AI agent team (simulation only): settings, prices, indicators, the walk-forward phase 8 signal,
and the trade simulator. Used by agent_packets.py, phase8_baseline.py and agent_score.py.

Nothing in this project places real orders. Every function that looks at a date D uses only data up to D,
except simulate_trade() and window_return(), which score a decision after the fact with the prices that followed.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

import fetch_prices as fp
import phase8_market_models as pm

ROOT = Path(__file__).resolve().parent
AGENTS = ROOT / "agents"
PROMPTS = AGENTS / "prompts"
OUT = ROOT / "data" / "agents"
MKT = ROOT / "data" / "market"


# ---------------------------------------------------------------- settings
def config():
    return json.loads((AGENTS / "config.json").read_text(encoding="utf-8"))


def prompts_version():
    """Short hash of every prompt file, so each scored run records which prompt wording produced it."""
    h = hashlib.sha1()
    for p in sorted(PROMPTS.glob("*.md")):
        h.update(p.name.encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:8]


def split_of(date, cfg):
    d = pd.Timestamp(date)
    for name, (a, b) in cfg["splits"].items():
        if pd.Timestamp(a) <= d <= pd.Timestamp(b):
            return name
    return "forward" if d >= pd.Timestamp(cfg["blind_before"]) else "pre"


# ---------------------------------------------------------------- data
def load_market():
    """USD prices (wide, one column per ticker), share volume (wide), universe table, daily factors."""
    wide, uni, fx = fp.load(MKT / "market.db")
    usd = fp.to_usd(wide, uni, fx)
    con = sqlite3.connect(MKT / "market.db")
    px = pd.read_sql("SELECT date, ticker, volume FROM prices", con, parse_dates=["date"])
    ff = pd.read_sql("SELECT * FROM factors_developed", con, parse_dates=["date"]).set_index("date")
    con.close()
    vol = px.pivot_table(index="date", columns="ticker", values="volume").sort_index()
    vol = vol.where(vol > 0)          # zero volume = a holiday or a data gap, not a real day with no trading

    return usd, vol, uni, ff


def companies(uni):
    return pm.companies(uni)


# ---------------------------------------------------------------- indicators (data up to D only)
def _ret(s, n):
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else None


def rsi(s, n=14):
    """Wilder's relative strength index from closes."""
    d = s.diff().dropna()
    if len(d) < n:
        return None
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    return 100.0 if dn == 0 else float(100 - 100 / (1 + up / dn))


def indicators(price, volume, soxx, date):
    """Numbers the Researcher works from, computed only from closes on or before `date`."""
    D = pd.Timestamp(date)
    s = price[price.index <= D].dropna()
    v = volume[volume.index <= D].dropna() if volume is not None else pd.Series(dtype=float)
    b = soxx[soxx.index <= D].dropna()
    if len(s) < 60:
        return None
    last = float(s.iloc[-1])
    out = dict(obs=len(s), close=last)
    for n in (20, 50, 200):
        out[f"ma{n}"] = float(s.iloc[-n:].mean()) if len(s) >= n else None
        out[f"vs_ma{n}_pct"] = 100 * (last / out[f"ma{n}"] - 1) if out[f"ma{n}"] else None
    for label, n in (("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252)):
        r = _ret(s, n)
        out[f"ret_{label}_pct"] = 100 * r if r is not None else None
        rb = _ret(b, n)
        out[f"sector_ret_{label}_pct"] = 100 * rb if rb is not None else None
    out["rsi14"] = rsi(s)
    lr = np.log(s).diff().dropna()
    out["vol20_ann_pct"] = float(100 * lr.iloc[-20:].std() * np.sqrt(252))
    out["vol120_ann_pct"] = float(100 * lr.iloc[-120:].std() * np.sqrt(252)) if len(lr) >= 120 else None
    out["volume_5d_vs_50d"] = float(v.iloc[-5:].mean() / v.iloc[-50:].mean()) if len(v) >= 50 and v.iloc[-50:].mean() > 0 else None
    for n in (20, 60, 252):
        w = s.iloc[-n:]
        out[f"high_{n}d"], out[f"low_{n}d"] = float(w.max()), float(w.min())
    out["from_252d_high_pct"] = 100 * (last / out["high_252d"] - 1)
    return out


# ---------------------------------------------------------------- phase 8, Model 1, walk-forward
def trailing_model1(usd, ff, date, cfg, tickers):
    """FF5 alpha and betas per stock from weekly returns that were knowable at `date`:
    complete weeks ending on or before `date`, and factor weeks lagged by factor_lag_days (Fama-French publishes late).
    Returns a DataFrame indexed by ticker with alpha_pct_yr, alpha_t, beta_mkt, beta_up_soxx, beta_down_soxx, weeks."""
    bc = cfg["baseline"]
    D = pd.Timestamp(date)
    cut = D - pd.Timedelta(days=bc["factor_lag_days"])
    w, fw = pm.weekly(usd[usd.index <= D], ff[ff.index <= cut])
    w = w[w.index <= D]
    fw = fw[fw.index <= cut].iloc[-bc["lookback_weeks"]:]
    cols = ["mkt_rf", "smb", "hml", "rmw", "cma"]
    rows = []
    for t in tickers:
        if t not in w:
            continue
        d = pd.concat([w[t], fw], axis=1, join="inner").dropna()
        if len(d) < bc["min_weeks"]:
            continue
        y = d[t].values - d["rf"].values
        b, se, _ = pm.ols(y, d[cols].values)
        s = pd.concat([w[t], w["SOXX"]], axis=1).dropna().iloc[-bc["lookback_weeks"]:]
        up, dn = s[s["SOXX"] > 0], s[s["SOXX"] < 0]
        rows.append(dict(ticker=t, weeks=len(d), alpha_pct_yr=100 * b[0] * 52, alpha_t=b[0] / se[0] if se[0] else 0.0,
                         beta_mkt=b[1],
                         beta_up_soxx=np.polyfit(up["SOXX"], up[t], 1)[0] if len(up) > 20 else np.nan,
                         beta_down_soxx=np.polyfit(dn["SOXX"], dn[t], 1)[0] if len(dn) > 20 else np.nan))
    return pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()


def shocks_before(date, ticker, within_days=None):
    """Phase 8 Model 4 supply shocks dated on or before `date`, with this stock's role in each."""
    D = pd.Timestamp(date)
    out = []
    for ev in pm.EVENTS:
        E = pd.Timestamp(ev["date"])
        if E > D or (within_days is not None and (D - E).days > within_days):
            continue
        role = ("expected loser" if ticker in ev["exposed"] else
                "expected winner" if ticker in ev["winners"] else "not in either group")
        out.append(dict(key=ev["key"], label=ev["label"], date=ev["date"], days_ago=(D - E).days, role=role))
    return out


# ---------------------------------------------------------------- scoring (uses prices after the decision)
def simulate_trade(price, date, action, size_pct, stop_pct, target_pct, max_hold, cfg):
    """Simulate one long trade decided at the close of `date`.

    Entry: the next close after `date`, plus slippage. Each later close is checked: down by stop_pct → exit (stop);
    up by target_pct → exit (target); after max_hold closes → exit (time). Exit price minus slippage, fees on both sides.
    Closes only (no intraday highs or lows), so a gap can exit beyond the stop, as it would in a real close-only system.
    Returns a dict; status is 'closed', 'open' (not enough later prices yet), 'no position' or 'incomplete'."""
    D = pd.Timestamp(date)
    s = price.dropna()
    after = s[s.index > D]
    base = dict(action=action, size_pct=size_pct, entry_date=None, entry_px=None, exit_date=None, exit_px=None,
                days=0, exit_reason="", ret_pct=0.0, portfolio_pct=0.0)
    if action != "BUY":
        return {**base, "status": "no position"}
    if after.empty:
        return {**base, "status": "open", "exit_reason": "no prices after decision yet"}
    fee, slip = cfg["fee_pct_per_side"] / 100, cfg["slippage_pct_per_side"] / 100
    e_date, e_close = after.index[0], float(after.iloc[0])
    path = after.iloc[1:max_hold + 1]
    exit_date, exit_close, reason = None, None, ""
    for d, px in path.items():
        move = px / e_close - 1
        if move <= -stop_pct / 100:
            exit_date, exit_close, reason = d, float(px), "stop"
            break
        if move >= target_pct / 100:
            exit_date, exit_close, reason = d, float(px), "target"
            break
    if exit_date is None:
        if len(path) < max_hold:
            last_d, last_px = (path.index[-1], float(path.iloc[-1])) if len(path) else (e_date, e_close)
            r = (last_px * (1 - slip)) / (e_close * (1 + slip)) - 1 - 2 * fee
            return {**base, "status": "open", "entry_date": e_date, "entry_px": e_close, "exit_date": last_d,
                    "exit_px": last_px, "days": len(path), "exit_reason": "still open (marked to last close)",
                    "ret_pct": 100 * r, "portfolio_pct": r * size_pct}
        exit_date, exit_close, reason = path.index[-1], float(path.iloc[-1]), "time"
    r = (exit_close * (1 - slip)) / (e_close * (1 + slip)) - 1 - 2 * fee
    return {**base, "status": "closed", "entry_date": e_date, "entry_px": e_close, "exit_date": exit_date,
            "exit_px": exit_close, "days": int((path.index <= exit_date).sum()), "exit_reason": reason,
            "ret_pct": 100 * r, "portfolio_pct": r * size_pct}


def window_dates(price, date, max_hold):
    """The window a NO TRADE decision is judged over: next close after `date` to max_hold closes later."""
    after = price.dropna()
    after = after[after.index > pd.Timestamp(date)]
    if len(after) < max_hold + 1:
        return None
    return after.index[0], after.index[max_hold]


def window_return(price, start, end, held=None):
    """Return of `price` from the close of `start` to the close of `end`, in percent.
    With `held` (a 0/1 Series by date: did the strategy hold it at the previous close?), only days it was held count."""
    s = price.dropna()
    s = s[(s.index >= start) & (s.index <= end)]
    if len(s) < 2:
        return None
    r = s.pct_change().dropna()
    if held is not None:
        h = held.reindex(r.index, method="ffill").fillna(0)
        r = r * h
    return 100 * float((1 + r).prod() - 1)
