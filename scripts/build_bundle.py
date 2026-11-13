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


def load_history(history_csv, trends_csv):
    """Season history for the cockpit's trend panel, from the files written by
    backfill_history.py and build_trends.py. Returns None if they are missing,
    in which case the panel shows a short 'not available yet' note instead."""
    import pandas as pd
    if not history_csv or not Path(history_csv).exists():
        return None
    h = pd.read_csv(history_csv)
    dates = sorted(h["date"].unique())

    def series(sub):
        s = sub.set_index("date")["real_score"].reindex(dates)
        return [None if pd.isna(v) else round(float(v), 2) for v in s]

    a1, a2 = {}, {}
    for name, sub in h[(h.level == "admin1") & (h.name != "Nouakchott")].groupby("name"):
        vals = series(sub)
        if any(v is not None for v in vals):
            a1[name] = vals
    for code, sub in h[h.level == "admin2"].groupby("code"):
        vals = series(sub)
        if any(v is not None for v in vals):
            a2[code] = {"wilaya": sub["wilaya"].iloc[0], "scores": vals}

    rows = []
    if trends_csv and Path(trends_csv).exists():
        t = pd.read_csv(trends_csv)
        rows = json.loads(t.astype(object).where(t.notna(), None).to_json(orient="records"))
    return {"dates": dates, "admin1": a1, "admin2": a2, "trends": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--as-of", default=None, help="Defaults to the latest dekad found in the NDVI CSV")
    parser.add_argument("--prev-state", default=None, help="Previous state JSON, for the alert diff")
    parser.add_argument("--admin1-geo", required=True)
    parser.add_argument("--admin2-geo", required=True)
    parser.add_argument("--fetch-manifest", default=None,
                         help="Optional data/fetch_manifest.json from fetch_hdx_data.py - carries HDX's "
                              "own 'last modified' timestamp per resource, distinct from the latest dekad "
                              "actually present in the data (the cockpit shows both, since they can differ).")
    parser.add_argument("--history", default=None, help="output/history_<ISO>.csv from backfill_history.py (for the trend panel)")
    parser.add_argument("--trends", default=None, help="output/trends_<ISO>.csv from build_trends.py (for the trend panel)")
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

    # The alert list describes the last REAL change in the data. It is saved when
    # that change is detected and reused when a run only republishes (for example
    # a template edit on unchanged data), so a redeploy never wipes the alert log.
    alerts_file = Path(args.out_dir) / f"alerts_{cfg['country_iso']}_latest.json"

    def load_saved_alerts():
        if alerts_file.exists():
            try:
                with open(alerts_file) as af:
                    return json.load(af).get("alerts", [])
            except Exception:
                return []
        return []

    alerts = []
    if args.prev_state and Path(args.prev_state).exists():
        with open(args.prev_state) as f:
            prev = json.load(f)
        if prev.get("content_hash") == state["content_hash"]:
            alerts = load_saved_alerts()
            print(f"No change since previous state (identical content_hash) - keeping the {len(alerts)} alert(s) saved from the last real change.")
        else:
            alerts = diff_states(prev, state, key="wilaya", level="admin1")
            alerts += diff_states(prev, state, key="PCODE", level="admin2")
            print(f"{len(alerts)} alert(s) generated vs. previous state.")
            Path(args.out_dir).mkdir(parents=True, exist_ok=True)
            with open(alerts_file, "w") as af:
                json.dump({"as_of": as_of, "generated_at": state["generated_at"], "alerts": alerts}, af)
    else:
        alerts = load_saved_alerts()
        print(f"No previous state supplied - reusing {len(alerts)} saved alert(s) if any (nothing to diff against).")

    trends = build_trends(cfg["ndvi_csv"], as_of, cfg.get("season_start", "2026-06-01"))

    with open(args.admin1_geo) as f:
        admin1_geo = json.load(f)
    with open(args.admin2_geo) as f:
        admin2_geo = json.load(f)

    fetch_manifest = None
    if args.fetch_manifest and Path(args.fetch_manifest).exists():
        with open(args.fetch_manifest) as f:
            fetch_manifest = json.load(f)
        print(f"Fetch manifest loaded: {args.fetch_manifest}")
    else:
        print("No fetch manifest found (expected if data/manual/ was used instead of the live HDX fetch) - "
              "the cockpit's 'HDX resource last touched' badge will be omitted for this run.")

    history = load_history(args.history, args.trends)
    if history:
        print(f"Trend history loaded: {len(history['dates'])} dekads, {len(history['admin1'])} wilayas, {len(history['admin2'])} moughataas")
    else:
        print("No trend history found - the cockpit's trend panel will show a 'not available yet' note.")

    bundle = {"state": state, "admin1_geo": admin1_geo, "admin2_geo": admin2_geo, "trends": trends,
              "alerts": alerts, "fetch_manifest": fetch_manifest, "history": history}

    out_path = Path(args.bundle_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(bundle, f)
    print(f"Bundle written: {out_path} ({out_path.stat().st_size:,} bytes)")

    # signal to the workflow whether anything actually changed
    changed = not (args.prev_state and Path(args.prev_state).exists()
                   and json.load(open(args.prev_state)).get("content_hash") == state["content_hash"])
    print(f"Changed since previous state: {'true' if changed else 'false'}")
    with open("bundle_changed.flag", "w") as f:
        f.write("true" if changed else "false")
