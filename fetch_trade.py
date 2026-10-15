"""
Phase 1 data pull for the Semiconductor Supply Chain Risk Engine.

Pulls monthly import data from UN Comtrade for three chipmaking inputs,
saves raw and cleaned CSVs, computes supplier concentration (HHI), and
plots South Korea's helium imports by supplier.

Run:  python fetch_trade.py            only fetches years that are missing, plus the last two years
                                        (countries revise recent months), and merges them in
      python fetch_trade.py --full     re-download everything
Needs the COMTRADE_KEY environment variable (GitHub Actions secret) or comtrade_key.txt in this folder.
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd

try:
    import comtradeapicall
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(f"Could not import comtradeapicall: {e!r}")

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
FIGS = ROOT / "figures"
for d in (RAW, PROC, FIGS):
    d.mkdir(parents=True, exist_ok=True)

# ---------------- settings ----------------
MATERIALS = {            # HS 6-digit codes
    "helium": "280429",  # rare gases other than argon (shared with neon, krypton, xenon)
    "gallium": "811292", # minor metals incl. gallium, unwrought / powders / scrap
    "hf": "281111",      # hydrogen fluoride
}
IMPORTERS = {            # Comtrade reporter codes
    "South Korea": "410",
    "Japan": "392",
    "United States": "842",
    "China": "156",
}
# Taiwan does not report to UN Comtrade (it appears only as partner "Other Asia, nes", code 490).
# Its imports can be rebuilt later from other countries' exports to partner 490.
START_YEAR = 2015
END_YEAR = pd.Timestamp.today().year
PAUSE_S = 1.2            # stay well under the API rate limit


def load_key() -> str:
    """Read the API key from comtrade_key.txt (the key alone, on the first line)."""
    key = os.environ.get("COMTRADE_KEY", "").strip()
    f = ROOT / "comtrade_key.txt"
    if not key and f.exists():
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                key = line.split("=", 1)[-1].strip().strip('"').strip("'")
                break
    if not key or key.lower().startswith("paste"):
        sys.exit("No API key found. Open comtrade_key.txt in Notepad, replace the placeholder with your key, and save.")
    return key


def periods_for(year: int) -> str:
    return ",".join(f"{year}{m:02d}" for m in range(1, 13))


REFRESH_YEARS = 2        # always re-fetch this many most recent years


def years_to_fetch(path: Path, full: bool = False) -> list:
    """Years missing from an existing raw file, plus the most recent REFRESH_YEARS."""
    every = list(range(START_YEAR, END_YEAR + 1))
    if full or not path.exists():
        return every
    try:
        have = set(pd.read_csv(path, usecols=["period"])["period"].astype(str).str[:4].astype(int))
    except Exception:  # noqa: BLE001
        return every
    recent = set(range(END_YEAR - REFRESH_YEARS + 1, END_YEAR + 1))
    return sorted((set(every) - have) | recent)


def merge_years(path: Path, new: pd.DataFrame, years: list) -> pd.DataFrame:
    """Replace the given years in an existing raw file with freshly downloaded rows."""
    if not path.exists():
        return new
    old = pd.read_csv(path)
    old = old[~old["period"].astype(str).str[:4].astype(int).isin(years)]
    old["period"] = old["period"].astype(str)
    if len(new):
        new = new.assign(period=new["period"].astype(str))
    return pd.concat([old, new], ignore_index=True).sort_values("period", kind="stable") if len(new) else old


def pull(key: str, cmd: str, reporter: str, years=None) -> pd.DataFrame:
    frames = []
    for year in (years if years is not None else range(START_YEAR, END_YEAR + 1)):
        for attempt in range(3):
            try:
                df = comtradeapicall.getFinalData(
                    key, typeCode="C", freqCode="M", clCode="HS",
                    period=periods_for(year), reporterCode=reporter, cmdCode=cmd,
                    flowCode="M", partnerCode=None, partner2Code=None,
                    customsCode=None, motCode=None, maxRecords=250000,
                    format_output="JSON", aggregateBy=None,
                    breakdownMode="classic", countOnly=None, includeDesc=True,
                )
                break
            except Exception as e:  # network hiccup or rate limit
                print(f"    retry {attempt + 1} after error: {e}")
                time.sleep(5 * (attempt + 1))
                df = None
        if df is not None and len(df):
            frames.append(df)
        time.sleep(PAUSE_S)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def clean(df: pd.DataFrame, material: str) -> pd.DataFrame:
    keep = {
        "period": "period", "reporterDesc": "importer", "partnerCode": "partner_code",
        "partnerDesc": "supplier", "netWgt": "net_kg", "qty": "qty",
        "qtyUnitAbbr": "qty_unit", "primaryValue": "value_usd",
    }
    out = df[[c for c in keep if c in df.columns]].rename(columns=keep)
    out["material"] = material
    out["date"] = pd.to_datetime(out["period"].astype(str), format="%Y%m")
    out = out[out["partner_code"] != 0]  # drop the "World" total row
    out["usd_per_kg"] = out["value_usd"] / out["net_kg"].where(out["net_kg"] > 0)
    return out.sort_values(["importer", "date", "value_usd"], ascending=[True, True, False])


def hhi(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["material", "importer", "date"])
    share = df["value_usd"] / g["value_usd"].transform("sum")
    tmp = df.assign(share_sq=share ** 2, share=share)
    out = tmp.groupby(["material", "importer", "date"]).agg(
        hhi=("share_sq", "sum"), total_usd=("value_usd", "sum"),
        top_share=("share", "max"), suppliers=("supplier", "nunique"),
    ).reset_index()
    top = tmp.loc[tmp.groupby(["material", "importer", "date"])["share"].idxmax(),
                  ["material", "importer", "date", "supplier"]].rename(columns={"supplier": "top_supplier"})
    return out.merge(top, on=["material", "importer", "date"])


def plot_korea_helium(df: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    k = df[(df["material"] == "helium") & (df["importer"].str.contains("Korea"))]
    if k.empty:
        print("No Korea helium rows to plot.")
        return
    top = k.groupby("supplier")["value_usd"].sum().nlargest(5).index
    k = k.assign(supplier=k["supplier"].where(k["supplier"].isin(top), "Other"))
    pivot = k.pivot_table(index="date", columns="supplier", values="value_usd", aggfunc="sum").fillna(0) / 1e6
    ax = pivot.plot.area(figsize=(11, 5), linewidth=0)
    ax.set_title("South Korea imports of HS 2804.29 (helium and other rare gases) by supplier")
    ax.set_ylabel("Import value, US$ million per month")
    ax.set_xlabel("")
    ax.legend(loc="upper left", frameon=False)
    plt.tight_layout()
    out = FIGS / "korea_helium_by_supplier.png"
    plt.savefig(out, dpi=150)
    print(f"Saved chart: {out}")


def main() -> None:
    key = load_key()
    full = "--full" in sys.argv
    all_clean = []
    for material, cmd in MATERIALS.items():
        for country, code in IMPORTERS.items():
            path = RAW / f"{material}_{code}.csv"
            years = years_to_fetch(path, full)
            print(f"Pulling {material} ({cmd}) imports for {country}, years {years[0]}-{years[-1]} ({len(years)})...")
            new = pull(key, cmd, code, years)
            raw = merge_years(path, new, years) if not new.empty else (pd.read_csv(path) if path.exists() else new)
            if raw.empty:
                print("    no data returned")
                continue
            raw.to_csv(path, index=False)
            c = clean(raw, material)
            all_clean.append(c)
            print(f"    {len(c):,} rows, {c['date'].min():%Y-%m} to {c['date'].max():%Y-%m}")
    if not all_clean:
        sys.exit("Nothing downloaded. Check the API key and your internet connection.")
    data = pd.concat(all_clean, ignore_index=True)
    data.to_csv(PROC / "imports_monthly.csv", index=False)
    conc = hhi(data)
    conc.to_csv(PROC / "supplier_concentration.csv", index=False)
    print(f"\nSaved {PROC / 'imports_monthly.csv'} ({len(data):,} rows)")
    print(f"Saved {PROC / 'supplier_concentration.csv'} ({len(conc):,} rows)")
    latest = conc.sort_values("date").groupby(["material", "importer"]).tail(1)
    print("\nLatest month, supplier concentration:")
    print(latest[["material", "importer", "date", "hhi", "top_supplier", "top_share"]]
          .to_string(index=False, formatters={"hhi": "{:.2f}".format, "top_share": "{:.0%}".format,
                                              "date": lambda d: f"{d:%Y-%m}"}))
    plot_korea_helium(data)


if __name__ == "__main__":
    main()
