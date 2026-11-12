#!/usr/bin/env python3
"""
backfill_history.py
====================
Rebuilds the engine's state snapshot for EVERY dekad in the season that
does not already have one, then compiles all snapshots into a single tidy
history file (output/history_<ISO>.csv) that the trend analysis reads.

Why this exists: HDX's "full" CSV always contains the complete record, so a
failed workflow run never loses data - it only leaves a gap in the saved
per-dekad snapshots. This script closes those gaps, so the trend analysis
has an unbroken series regardless of which scheduled runs failed.

It is idempotent: existing snapshots are kept (use --force to rebuild them),
so running it every time is safe and cheap once the history is complete.

Note: backfilled dekads are computed from the data as it exists NOW, not as
it looked at the time. If HDX has since corrected past values, the history
reflects the corrected values - which is what you want for a trend.
"""
import sys
import json
import argparse
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from praps2_engine import build_state  # noqa: E402


def season_dekads(ndvi_csv, season_start):
    df = pd.read_csv(ndvi_csv, usecols=["date", "adm_level"], parse_dates=["date"])
    dates = sorted(df.loc[(df.adm_level == 1) & (df.date >= pd.Timestamp(season_start)), "date"].unique())
    return [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates]


def state_path(out_dir, iso, as_of):
    return Path(out_dir) / f"state_{iso}_{as_of}.json"


def flatten(state):
    rows = []
    for r in state["admin1"]:
        rows.append({"date": state["as_of"], "level": "admin1", "code": r.get("PCODE"), "name": r.get("wilaya"),
                     "wilaya": r.get("wilaya"), "vci_season_avg": r.get("vci_season_avg"), "rain3mo": r.get("rain3mo"),
                     "real_score": r.get("real_score"), "real_tier": r.get("real_tier"), "psvi": r.get("psvi")})
    for r in state["admin2"]:
        rows.append({"date": state["as_of"], "level": "admin2", "code": r.get("PCODE"), "name": r.get("PCODE"),
                     "wilaya": r.get("wilaya"), "vci_season_avg": r.get("vci_season_avg"), "rain3mo": r.get("rain3mo"),
                     "real_score": r.get("real_score"), "real_tier": r.get("real_tier"), "psvi": None})
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out-dir", default="output")
    ap.add_argument("--force", action="store_true", help="Rebuild snapshots even if they already exist")
    args = ap.parse_args()

    cfg = json.load(open(args.config))
    iso = cfg["country_iso"]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dekads = season_dekads(cfg["ndvi_csv"], cfg["season_start"])
    print(f"Dekads in season so far (from {cfg['season_start']}): {len(dekads)} -> {dekads[0]} .. {dekads[-1]}")

    built, kept = [], []
    for as_of in dekads:
        p = state_path(out_dir, iso, as_of)
        if p.exists() and not args.force:
            kept.append(as_of)
            continue
        state = build_state(cfg, as_of)
        with open(p, "w") as f:
            json.dump(state, f, indent=2)
        built.append(as_of)
        print(f"  backfilled {as_of}")

    print(f"Snapshots kept: {len(kept)} | newly built: {len(built)}")

    # Compile every snapshot (old and new) into one history file
    rows = []
    for as_of in dekads:
        with open(state_path(out_dir, iso, as_of)) as f:
            rows.extend(flatten(json.load(f)))
    hist = pd.DataFrame(rows)
    hist_path = out_dir / f"history_{iso}.csv"
    hist.to_csv(hist_path, index=False)
    print(f"History written: {hist_path} ({len(hist):,} rows, {hist['date'].nunique()} dekads)")
