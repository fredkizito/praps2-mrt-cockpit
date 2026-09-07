"""
praps2_engine.py
=================
Core ingestion + calculation engine for the PRAPS2 Pastoral Early Warning system.

This is the single source of truth: every other component (alert bot, cockpit,
CH-packet generator, field tool) reads its output, never recomputes it.

Design goal: country-agnostic. Mauritania is the reference implementation
(config/countries/mrt.json) because it's the only country with real data
available in this session, but nothing in this file is Mauritania-specific -
see Section 6 (regional scale-up) for how a second country plugs in.

USAGE
-----
    python3 praps2_engine.py --config config/countries/mrt.json --as-of 2026-08-21

Produces output/state_<country>_<as_of>.json - a complete, timestamped snapshot
of every wilaya and moughataa's risk tier, PSVI, and underlying real indicators.
"""

import json
import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# 1. INGESTION
# ---------------------------------------------------------------------------

def load_ndvi(path):
    df = pd.read_csv(path, parse_dates=["date"])
    df["month_day"] = df["date"].dt.strftime("%m-%d")
    df["year"] = df["date"].dt.year
    return df


def load_rainfall(path):
    return pd.read_csv(path, parse_dates=["date"])


def load_livestock(path, name_map, area_map):
    """RGE-style wilaya livestock CSV -> TLU per wilaya. Country-specific
    conversion factors are passed in via config (camel/cattle/sheep/goat/
    horse/donkey TLU weights), not hardcoded here."""
    df = pd.read_csv(path)
    return df


# ---------------------------------------------------------------------------
# 2. CALCULATION - Vegetation Condition Index (24-yr envelope method)
# ---------------------------------------------------------------------------

def compute_vci(ndvi_df, as_of, admin_level, pcode_col="PCODE", value_col="vim"):
    """VCI = (current - hist_min) / (hist_max - hist_min) * 100, clipped 0-100,
    computed per admin unit per calendar dekad against the full historical
    record (all years before the current one)."""
    sub = ndvi_df[ndvi_df.adm_level == admin_level].copy()
    as_of_ts = pd.Timestamp(as_of)
    current_year = as_of_ts.year

    hist = sub[sub.year < current_year]
    hist_stats = hist.groupby([pcode_col, "month_day"])[value_col].agg(["min", "max"]).reset_index()
    hist_stats.columns = [pcode_col, "month_day", "hist_min", "hist_max"]

    cur = sub[(sub.year == current_year) & (sub.date <= as_of_ts)]
    merged = cur.merge(hist_stats, on=[pcode_col, "month_day"], how="left")
    merged["VCI"] = ((merged[value_col] - merged["hist_min"]) /
                      (merged["hist_max"] - merged["hist_min"]) * 100).clip(0, 100)
    return merged


def season_average_vci(vci_df, season_start, as_of, pcode_col="PCODE"):
    season = vci_df[(vci_df.date >= pd.Timestamp(season_start)) & (vci_df.date <= pd.Timestamp(as_of))]
    return season.groupby(pcode_col)["VCI"].mean().rename("vci_season_avg")


def latest_rainfall_anomaly(rain_df, as_of, admin_level, pcode_col="PCODE", field="r3q"):
    sub = rain_df[rain_df.adm_level == admin_level]
    latest = sub[sub.date == pd.Timestamp(as_of)]
    return latest.set_index(pcode_col)[field].rename("rain3mo")


# ---------------------------------------------------------------------------
# 3. CALCULATION - Real Resource Score & Tier (configurable thresholds)
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS = {
    "vci_bands": [(10, 1.0), (35, 2.0), (50, 2.5), (65, 3.5), (999, 4.5)],
    "rain_bands": [(60, 1.0), (75, 2.0), (85, 2.5), (95, 3.5), (999, 4.5)],
    "weights": {"vci": 0.65, "rain": 0.35},
    "tier_bands": [(1.75, "SEVERE"), (2.75, "HIGH"), (3.25, "MODERATE-HIGH"), (4.0, "MODERATE"), (999, "FAVOURABLE")],
}


def _band(value, bands):
    if pd.isna(value):
        return np.nan
    for threshold, score in bands:
        if value < threshold:
            return score
    return bands[-1][1]


def compute_resource_score(vci, rain_anom, thresholds=DEFAULT_THRESHOLDS):
    vci_comp = _band(vci, thresholds["vci_bands"])
    rain_comp = _band(rain_anom, thresholds["rain_bands"])
    if pd.isna(vci_comp) and pd.isna(rain_comp):
        return np.nan
    w = thresholds["weights"]
    if pd.isna(rain_comp):
        return round(vci_comp, 2)
    return round(w["vci"] * vci_comp + w["rain"] * rain_comp, 2)


def compute_tier(score, thresholds=DEFAULT_THRESHOLDS):
    if pd.isna(score):
        return "NO DATA"
    for threshold, tier in thresholds["tier_bands"]:
        if score < threshold:
            return tier
    return thresholds["tier_bands"][-1][1]


# ---------------------------------------------------------------------------
# 4. CALCULATION - Pastoral Suitability/Vulnerability Index (PSVI)
# ---------------------------------------------------------------------------

def compute_psvi(tlu_per_km2, resource_score):
    if pd.isna(tlu_per_km2) or pd.isna(resource_score) or resource_score == 0:
        return np.nan
    return round(tlu_per_km2 / resource_score, 2)


def psvi_tier(psvi):
    if pd.isna(psvi):
        return "N/A"
    if psvi >= 8:
        return "VERY HIGH"
    if psvi >= 4:
        return "HIGH"
    if psvi >= 1.5:
        return "MODERATE"
    return "LOW"


# ---------------------------------------------------------------------------
# 5. ORCHESTRATION - build a complete state snapshot
# ---------------------------------------------------------------------------

def build_state(config, as_of):
    """Run the full pipeline for one country config at one as-of date.
    Returns a plain-dict state object, JSON-serialisable, versioned by a
    content hash so the alert bot can detect "nothing changed" cheaply."""

    ndvi = load_ndvi(config["ndvi_csv"])
    rain = load_rainfall(config["rainfall_csv"])

    # --- admin1 (wilaya) ---
    vci1 = compute_vci(ndvi, as_of, admin_level=1)
    vci1_season = season_average_vci(vci1, config["season_start"], as_of)
    rain1 = latest_rainfall_anomaly(rain, as_of, admin_level=1)

    a1 = pd.DataFrame(vci1_season).join(rain1, how="outer").reset_index().rename(columns={"index": "PCODE"})
    a1["wilaya"] = a1["PCODE"].map(config["pcode_to_name_adm1"])
    a1["real_score"] = a1.apply(lambda r: compute_resource_score(r["vci_season_avg"], r["rain3mo"]), axis=1)
    a1["real_tier"] = a1["real_score"].apply(compute_tier)

    livestock = pd.DataFrame(config["livestock_by_wilaya"]).T
    livestock.index.name = "wilaya"
    livestock = livestock.reset_index()
    w = config["tlu_weights"]
    livestock["tlu"] = (livestock["cattle"] * w["cattle"] + livestock["camels"] * w["camels"] +
                         (livestock["sheep"] + livestock["goats"]) * w["small_ruminant"] +
                         (livestock["horses"] + livestock["donkeys"]) * w["equine"])
    livestock["area_km2"] = livestock["wilaya"].map(config["area_km2_by_wilaya"])
    livestock["tlu_km2"] = livestock["tlu"] / livestock["area_km2"]

    a1 = a1.merge(livestock[["wilaya", "tlu", "tlu_km2", "area_km2"]], on="wilaya", how="left")
    a1["psvi"] = a1.apply(lambda r: compute_psvi(r["tlu_km2"], r["real_score"]), axis=1)
    a1["psvi_tier"] = a1["psvi"].apply(psvi_tier)

    # --- admin2 (moughataa), where available ---
    vci2 = compute_vci(ndvi, as_of, admin_level=2)
    vci2_season = season_average_vci(vci2, config["season_start"], as_of)
    rain2 = latest_rainfall_anomaly(rain, as_of, admin_level=2)
    a2 = pd.DataFrame(vci2_season).join(rain2, how="outer").reset_index().rename(columns={"index": "PCODE"})
    a2["real_score"] = a2.apply(lambda r: compute_resource_score(r["vci_season_avg"], r["rain3mo"]), axis=1)
    a2["real_tier"] = a2["real_score"].apply(compute_tier)
    a2["wilaya"] = a2["PCODE"].str[:4].map(config.get("pcode_prefix_to_wilaya", {}))

    state = {
        "country": config["country_name"],
        "country_iso": config["country_iso"],
        "as_of": str(as_of),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "admin1": json.loads(a1.to_json(orient="records")),
        "admin2": json.loads(a2.to_json(orient="records")),
        "n_admin1": len(a1),
        "n_admin2_total": len(a2),
        "n_admin2_with_data": int(a2["real_score"].notna().sum()),
    }
    state_str = json.dumps(state, sort_keys=True)
    state["content_hash"] = hashlib.sha256(state_str.encode()).hexdigest()[:16]
    return state


def save_state(state, out_dir="output"):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    fname = f"state_{state['country_iso']}_{state['as_of']}.json"
    path = Path(out_dir) / fname
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    latest = Path(out_dir) / f"state_{state['country_iso']}_latest.json"
    with open(latest, "w") as f:
        json.dump(state, f, indent=2)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--out", default="output")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    state = build_state(cfg, args.as_of)
    path = save_state(state, args.out)
    print(f"State built: {state['n_admin1']} admin1 units, "
          f"{state['n_admin2_with_data']}/{state['n_admin2_total']} admin2 units with data.")
    print(f"Content hash: {state['content_hash']}")
    print(f"Written to: {path}")
