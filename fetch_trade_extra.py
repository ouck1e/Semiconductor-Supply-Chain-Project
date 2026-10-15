"""
Phase 8 exposure, data step: more countries' imports of helium/rare gases, gallium and HF, so every big fab
location is covered.

  1. New importers that report to Comtrade: Singapore, Germany, Ireland, Israel, Malaysia
     -> data/raw/<material>_<code>.csv  (same format as phase 1, so phase 2 and 3 pick them up too)
  2. Taiwan, which does not report: rebuilt from every other country's EXPORTS to partner 490 ("Other Asia, nes")
     -> data/raw_mirror/<material>_490.csv  (kept separate: export values are FOB, imports CIF, so mirror values
        run ~5-10% lower, and re-exports through third countries are missed)

Run:  python fetch_trade_extra.py   (or double-click run_trade_extra.bat; needs comtrade_key.txt and internet,
      about 15 minutes the first time). Later runs fetch only missing years plus the last two; --full re-downloads.
"""
import sys
import time
from pathlib import Path

import pandas as pd

import fetch_trade as ft          # reuses the key loader, settings and retry logic from phase 1

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
MIRROR = ROOT / "data" / "raw_mirror"
MIRROR.mkdir(parents=True, exist_ok=True)

NEW_IMPORTERS = {"Singapore": "702", "Germany": "276", "Ireland": "372", "Israel": "376", "Malaysia": "458"}
TAIWAN = "490"


def pull_mirror(key, cmd, years=None):
    """All reporters' exports to Taiwan, monthly, 2015 on."""
    import comtradeapicall
    frames = []
    for year in (years if years is not None else range(ft.START_YEAR, ft.END_YEAR + 1)):
        df = None
        for attempt in range(3):
            try:
                df = comtradeapicall.getFinalData(
                    key, typeCode="C", freqCode="M", clCode="HS", period=ft.periods_for(year),
                    reporterCode=None, cmdCode=cmd, flowCode="X", partnerCode=TAIWAN, partner2Code=None,
                    customsCode=None, motCode=None, maxRecords=250000, format_output="JSON",
                    aggregateBy=None, breakdownMode="classic", countOnly=None, includeDesc=True)
                break
            except Exception as e:  # noqa: BLE001
                print(f"    retry {attempt + 1} after error: {e}")
                time.sleep(5 * (attempt + 1))
        if df is not None and len(df):
            frames.append(df)
        time.sleep(ft.PAUSE_S)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    # flip to the importer's point of view so it reads like phase-1 import files
    raw = raw.rename(columns={"reporterCode": "exporterCode", "reporterDesc": "exporterDesc"})
    raw["reporterCode"] = int(TAIWAN)
    raw["reporterDesc"] = "Taiwan (mirror)"
    raw["partnerCode"] = raw["exporterCode"]
    raw["partnerDesc"] = raw["exporterDesc"]
    raw["flowCode"] = "M (mirror of X)"
    return raw


def complete(path):
    """A file counts as done if it has data for every year from START_YEAR to last year."""
    if not path.exists():
        return False
    try:
        y = set(pd.read_csv(path, usecols=["period"])["period"].astype(str).str[:4].astype(int))
    except Exception:  # noqa: BLE001
        return False
    return set(range(ft.START_YEAR, ft.END_YEAR)) <= y


def main():
    key = ft.load_key()
    full = "--full" in sys.argv
    for material, cmd in ft.MATERIALS.items():
        for country, code in NEW_IMPORTERS.items():
            path = RAW / f"{material}_{code}.csv"
            years = ft.years_to_fetch(path, full)
            print(f"Pulling {material} ({cmd}) imports for {country}, {len(years)} year(s)...", flush=True)
            new = ft.pull(key, cmd, code, years)
            if new.empty:
                print("    no new data returned")
                continue
            ft.merge_years(path, new, years).to_csv(path, index=False)
            print(f"    {len(new):,} new rows")
        path = MIRROR / f"{material}_{TAIWAN}.csv"
        years = ft.years_to_fetch(path, full)
        print(f"Pulling {material} ({cmd}) exports TO Taiwan from all reporters (mirror), {len(years)} year(s)...", flush=True)
        m = pull_mirror(key, cmd, years)
        if m.empty:
            print("    no new data returned")
            continue
        ft.merge_years(path, m, years).to_csv(path, index=False)
        print(f"    {len(m):,} new rows from {m['partnerDesc'].nunique()} exporting countries")
    print("\nDone. Next: python exposure_model.py")


if __name__ == "__main__":
    sys.exit(main())
