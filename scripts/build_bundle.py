#!/usr/bin/env python3
"""
build_bundle.py
=================
Runs the engine against freshly-fetched CSVs, diffs against the last
committed state to generate alerts, and assembles cockpit/bundle.json -
the single file the cockpit template needs to render everything.

Boundaries (admin1.json, admin2.json) are NOT rebuilt here - they don't
change dekad to dekad, so they stay as committed static files. Only the
data-derived pieces (state, trends, alerts) are regenerated each run.
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

from praps2_engine import load_ndvi, compute_vci, build_state, save_state  # noqa: E402
from alert_bot import diff_states  # noqa: E402


def latest_dekad_in(ndvi_csv):
    import pandas as pd
    df = pd.read_csv(ndvi_csv, parse_dates=["date"])
    return df["date"].max().strftime("%Y-%m-%d")


def build_trends(ndvi_csv, as_of, season_start="2026-06-01"):
    """Per-unit VCI trend series (admin1 + admin2), for the cockpit's
    trend chart. Mirrors the one-off script used when this pipeline was
    first built, packaged here as a reusable function."""
    import pandas as pd
    ndvi = load_ndvi(ndvi_csv)
    trends = {}
    for level in (1, 2):
        vci = compute_vci(ndvi, as_of, admin_level=level)
        vci = vci[vci.date >= "2026-01-01"].sort_values("date")
        for pcode, sub in vci.groupby("PCODE"):
            trends[pcode] = [
                {"d": d.strftime("%m-%d"), "vci": round(float(v), 1) if pd.notna(v) else None}
                for d, v in zip(sub["date"], sub["VCI"])
            ]
    return trends


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--as-of", default=None, help="Defaults to the latest dekad found in the NDVI CSV")
    parser.add_argument("--prev-state", default=None, help="Previous state JSON, for the alert diff")
    parser.add_argument("--admin1-geo", required=True)
    parser.add_argument("--admin2-geo", required=True)
    parser.add_argument("--out-dir", default="output")
    parser.add_argument("--bundle-out", default="cockpit/bundle.json")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    as_of = args.as_of or latest_dekad_in(cfg["ndvi_csv"])
    print(f"Building state for as-of = {as_of}")

    state = build_state(cfg, as_of)
    state_path = save_state(state, args.out_dir)
    print(f"State written: {state_path} (content_hash={state['content_hash']})")

    alerts = []
    if args.prev_state and Path(args.prev_state).exists():
        with open(args.prev_state) as f:
            prev = json.load(f)
        if prev.get("content_hash") == state["content_hash"]:
            print("No change since previous state (identical content_hash) - skipping alert generation.")
        else:
            alerts = diff_states(prev, state, key="wilaya", level="admin1")
            alerts += diff_states(prev, state, key="PCODE", level="admin2")
            print(f"{len(alerts)} alert(s) generated vs. previous state.")
    else:
        print("No previous state supplied - first run, no alerts to diff.")

    trends = build_trends(cfg["ndvi_csv"], as_of, cfg.get("season_start", "2026-06-01"))

    with open(args.admin1_geo) as f:
        admin1_geo = json.load(f)
    with open(args.admin2_geo) as f:
        admin2_geo = json.load(f)

    bundle = {"state": state, "admin1_geo": admin1_geo, "admin2_geo": admin2_geo, "trends": trends, "alerts": alerts}

    out_path = Path(args.bundle_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(bundle, f)
    print(f"Bundle written: {out_path} ({out_path.stat().st_size:,} bytes)")

    # signal to the workflow whether anything actually changed
    changed = not (args.prev_state and Path(args.prev_state).exists()
                   and json.load(open(args.prev_state)).get("content_hash") == state["content_hash"])
    print(f"::set-output name=changed::{'true' if changed else 'false'}")
    with open("bundle_changed.flag", "w") as f:
        f.write("true" if changed else "false")
