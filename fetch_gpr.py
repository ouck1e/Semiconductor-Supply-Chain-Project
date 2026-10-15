"""
Download the Caldara-Iacoviello Geopolitical Risk (GPR) index, monthly, and save a tidy CSV.

Run:  python fetch_gpr.py
Writes data/external/gpr_raw.xls and data/external/gpr_monthly.csv
Data: https://www.matteoiacoviello.com/gpr.htm  (CC BY; cite Caldara & Iacoviello, AER 2022)
"""
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "external"
OUT.mkdir(parents=True, exist_ok=True)

today = pd.Timestamp.today()
stamps = [(today - pd.DateOffset(months=k)).strftime("%Y%m") for k in range(0, 4)]
CANDIDATES = ["https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"] + [
    f"https://www.matteoiacoviello.com/gpr_files/data_gpr_export_{s}.xls" for s in stamps]


def download() -> Path:
    raw = OUT / "gpr_raw.xls"
    for url in CANDIDATES:
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 (research script)"})
            if r.status_code == 200 and len(r.content) > 50_000:
                raw.write_bytes(r.content)
                print(f"Downloaded {url} ({len(r.content):,} bytes)")
                return raw
            print(f"  {url}: HTTP {r.status_code}, {len(r.content)} bytes")
        except Exception as e:
            print(f"  {url}: {e}")
    sys.exit("Could not download the GPR file. Download the Excel file by hand from "
             "https://www.matteoiacoviello.com/gpr.htm and save it as data/external/gpr_raw.xls, then rerun.")


def main():
    raw = OUT / "gpr_raw.xls"
    if not raw.exists() or "--refresh" in sys.argv or raw.stat().st_mtime < (today - pd.Timedelta(days=20)).timestamp():
        raw = download()
    df = pd.read_excel(raw, sheet_name=0)
    date_col = next(c for c in df.columns if str(c).lower() in ("month", "date"))
    df["date"] = pd.to_datetime(df[date_col]).dt.to_period("M").dt.to_timestamp()
    keep = ["date"] + [c for c in df.columns if c in ("GPR", "GPRT", "GPRA") or str(c).startswith("GPRC_")]
    out = df[keep].dropna(subset=["GPR"]).sort_values("date")
    out = out[out["date"] >= "2005-01-01"]
    out.to_csv(OUT / "gpr_monthly.csv", index=False)
    countries = sorted(c.replace("GPRC_", "") for c in out.columns if c.startswith("GPRC_"))
    print(f"Saved data/external/gpr_monthly.csv: {len(out)} months, {out['date'].min():%Y-%m} to {out['date'].max():%Y-%m}")
    print(f"Country indexes ({len(countries)}): {', '.join(countries)}")


if __name__ == "__main__":
    main()
