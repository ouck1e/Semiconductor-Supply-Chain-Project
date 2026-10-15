"""
Phase 4: how much helium, neon, HF and gallium one wafer uses, and what that costs today.

Fabs don't publish these numbers, so each input gets a low / central / high range built from
published inventories, industry-wide totals divided by wafer output, and (for HF) your own Comtrade data.
Every number below carries its source in a comment so it can be challenged.

Reads   data/processed/imports_classified.csv   (from phase2_event_study.py)
Writes  data/processed/per_wafer_usage.csv      one row per input: amounts, unit price, $ per wafer, inventory days
        data/processed/hf_crosscheck.csv        HF bottom-up vs. Korea's Comtrade imports

Run:  python phase4_wafer_usage.py     (no internet or API key needed)
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
PROC = ROOT / "data" / "processed"

# ---------- wafer output ----------
# SEMI: 12,973 million in² of silicon shipped in 2025. One 300 mm wafer = pi * (150 mm)^2 = 109.6 in².
WORLD_WAFERS_2025 = 12_973e6 / 109.6                 # ~118M 300 mm-equivalent wafers a year
# SEMI 300 mm fab capacity, 2025 projection: Korea 24%, Taiwan 21%, China 23%, Japan 12% of 9.2M wafers/month.
KOREA_SHARE = 0.24
KOREA_WAFERS = KOREA_SHARE * WORLD_WAFERS_2025       # ~28M wafers a year

# ---------- physical constants (0 °C, 1 atm) ----------
HELIUM_KG_PER_M3 = 0.1786
NEON_KG_PER_M3 = 0.9002


def unit_values(df: pd.DataFrame) -> dict:
    """Latest full-year import unit values from your Comtrade data (reported quantities only)."""
    df = df.copy()
    df["year"] = df["date"].dt.year
    out = {}

    def uv(series, importer, year):
        g = df[(df.series == series) & (df.importer == importer) & (df.year == year)
               & df.net_kg_reported.gt(0)]
        return g.value_usd.sum() / g.net_kg_reported.sum()

    # helium: Korea and Japan 2025, $/kg -> $/m³
    he = [uv("helium", imp, 2025) for imp in ("Rep. of Korea", "Japan")]
    out["helium"] = dict(unit="US$ per m³", low=min(he) * HELIUM_KG_PER_M3,
                         central=sum(he) / 2 * HELIUM_KG_PER_M3, high=max(he) * HELIUM_KG_PER_M3,
                         source="Korea & Japan 2025 Comtrade helium unit values")
    # neon: Ukraine's 2013-2021 export unit values ($52-228/m³, plan doc) for low/high;
    # central = Korea's 2025 rare-gas unit value (still includes some krypton/xenon, so it leans high)
    ne_kr = uv("rare gas", "Rep. of Korea", 2025) * NEON_KG_PER_M3
    out["neon"] = dict(unit="US$ per m³", low=52.0, central=min(ne_kr, 228.0), high=228.0,
                       source="Ukraine 2013-21 export unit values; Korea 2025 rare-gas unit value")
    # HF: Korea 2025 import unit value (as traded, mixed concentrations)
    hf = uv("hf", "Rep. of Korea", 2025)
    out["hf"] = dict(unit="US$ per kg", low=hf * 0.8, central=hf, high=hf * 1.3,
                     source="Korea 2025 Comtrade HF unit value; ±20-30% for grade "
                            "(2026 suppliers raised EG-HF 20-30%)")
    # gallium: US & Japan 2025 unit values, HS 8112.92 (noisy: other minor metals mixed in)
    ga = [uv("gallium", imp, 2025) for imp in ("USA", "Japan")]
    out["gallium"] = dict(unit="US$ per kg", low=min(ga), central=sum(ga) / 2, high=max(ga),
                          source="US & Japan 2025 Comtrade HS 8112.92 unit values (noisy proxy)")
    return out


def hf_crosscheck(df: pd.DataFrame) -> pd.DataFrame:
    """Top-down HF per wafer from Korea's imports. Korea's HF comes mostly from abroad
    (China, Japan), so imports approximate total supply; chips are only part of it (displays,
    solar, glass and steel also use HF), so all-imports / wafers is an upper bound."""
    k = df[(df.series == "hf") & (df.importer == "Rep. of Korea")].copy()
    k["year"] = k["date"].dt.year
    yr = k.groupby("year").net_kg_reported.sum() / 1e6                       # kt
    jp = k[k.supplier == "Japan"].groupby("year").net_kg_reported.sum() / 1e6
    rows = [
        dict(measure="All Korea HF imports, 2023-2025 average", kt_per_year=yr.loc[2023:2025].mean()),
        dict(measure="Japan's HF to Korea, 2016-2018 average (chip + display grade, before the 2019 curbs)",
             kt_per_year=jp.loc[2016:2018].mean()),
        dict(measure="Japan's HF to Korea, 2025", kt_per_year=jp.loc[2025]),
    ]
    out = pd.DataFrame(rows)
    out["korea_wafers_m"] = KOREA_WAFERS / 1e6
    out["kg_per_wafer"] = out.kt_per_year * 1e6 / KOREA_WAFERS
    return out


def usage_table(cross: pd.DataFrame) -> pd.DataFrame:
    hf_all = cross.kg_per_wafer.iloc[0]
    hf_japan = cross.kg_per_wafer.iloc[1]
    rows = [
        # Helium. Low: net fresh helium after 80-95% recapture. Central: chips' 21-24% of ~190M m³ world
        # supply / wafers. High: Williams, Ayres & Heller 2002 inventory with no recapture, scaled to 300 mm.
        dict(input="helium", unit="m³ per 300 mm wafer", low=0.03, central=0.36, high=0.67,
             inventory_days=42, inventory_source="~6 weeks (Tom's Hardware)",
             basis="Low: after 80-95% recapture. Central: chips' 21-24% of ~190M m³ world supply / wafers. "
                   "High: Williams 2002, no recapture"),
        # Neon. High: Techcet's 540 t of chip-industry neon in 2021 / 2021 wafers. Low: after laser
        # gas-saving cuts (up to 75%) and ~70% in-fab recycling. Converted L -> m³ below.
        dict(input="neon", unit="m³ per 300 mm wafer", low=0.0003, central=0.0023, high=0.0046,
             inventory_days=60, inventory_source="~2 months (SFA Oxford)",
             basis="High: Techcet 540 t (2021) / wafers. Low: laser gas savings + in-fab recycling"),
        # HF, now in kg AS TRADED (mixed concentrations, the Comtrade unit), not 100% HF.
        # Low: Williams 2002's ~150 g of pure HF = ~0.3 kg as 49% acid. Central: Japan's pre-2019 HF to
        # Korea / Korea's wafers (that HF also served display fabs, so it leans high; Chinese trade press
        # quotes 2.5-3 kg EG-HF per wafer, so not by much). High: ALL Korea HF imports / Korea's wafers.
        dict(input="hf", unit="kg HF as traded per 300 mm wafer", low=0.3, central=round(hf_japan, 2),
             high=round(hf_all, 2), inventory_days=30,
             inventory_source="Samsung: 'a month at tops' (JoongAng Daily, Jul 2019)",
             basis="Low: Williams 2002 (150 g pure HF). Central: Japan's 2016-18 HF to Korea / Korean wafers. "
                   "High: all Korean HF imports / Korean wafers"),
        # Gallium: not used in silicon logic/memory; only RF and power fabs.
        dict(input="gallium (GaAs RF)", unit="kg Ga per 150 mm wafer", low=0.061, central=0.077, high=0.102,
             inventory_days=None, inventory_source="",
             basis="Geometry: 675 µm wafer holds 31 g Ga / 30-50% crystal-to-wafer yield (assumed)"),
        dict(input="gallium (GaN-on-Si power)", unit="kg Ga per 200 mm wafer", low=0.0011, central=0.0040,
             high=0.0129, inventory_days=None, inventory_source="",
             basis="Geometry: 2-8 µm GaN / 10-30% MOCVD gallium use (assumed)"),
    ]
    return pd.DataFrame(rows)


def main():
    df = pd.read_csv(PROC / "imports_classified.csv", parse_dates=["date"])
    prices = unit_values(df)
    cross = hf_crosscheck(df)
    use = usage_table(cross)

    key = {"helium": "helium", "neon": "neon", "hf": "hf",
           "gallium (GaAs RF)": "gallium", "gallium (GaN-on-Si power)": "gallium"}
    for col in ("low", "central", "high"):
        use[f"price_{col}"] = [prices[key[i]][col] for i in use.input]
    use["price_unit"] = [prices[key[i]]["unit"] for i in use.input]
    use["price_source"] = [prices[key[i]]["source"] for i in use.input]
    use["usd_per_wafer_central"] = use.central * use.price_central
    use["usd_per_wafer_low"] = use.low * use.price_low
    use["usd_per_wafer_high"] = use.high * use.price_high

    use.to_csv(PROC / "per_wafer_usage.csv", index=False)
    cross.to_csv(PROC / "hf_crosscheck.csv", index=False)

    pd.set_option("display.width", 200)
    print(f"Wafers: world {WORLD_WAFERS_2025/1e6:.0f}M, Korea {KOREA_WAFERS/1e6:.1f}M per year (300 mm-equivalent)\n")
    print("HF cross-check against Korea's Comtrade imports")
    print(cross.round(2).to_string(index=False))
    print("\nPer-wafer usage and cost at today's prices")
    print(use[["input", "unit", "low", "central", "high", "price_central", "price_unit",
               "usd_per_wafer_low", "usd_per_wafer_central", "usd_per_wafer_high",
               "inventory_days"]].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
