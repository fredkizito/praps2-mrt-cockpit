#!/usr/bin/env python3
"""
build_trends.py
================
Turns output/history_<ISO>.csv (built by backfill_history.py) into:
  - output/trends_<ISO>.csv  : one row per wilaya with start/latest score,
                               overall change, change over the last 3 dekads,
                               and a plain-language direction label
  - output/trends_<ISO>.png  : small-multiples chart of the real resource
                               score over the season, with tier thresholds

Direction labels use a +/-0.25 score band so that a single-step wobble in
one dekad is not reported as a real trend.
"""
import argparse
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BAND = 0.25
TIER_LINES = [(1.75, "SEVERE", "#B23A32"), (2.75, "HIGH", "#E07B2A"), (3.25, "MOD-HIGH", "#E8A83A"), (4.0, "MODERATE", "#E5C93E")]
NAVY = "#002244"


def label(delta):
    if pd.isna(delta):
        return "n/a"
    if delta <= -BAND:
        return "Worsening"
    if delta >= BAND:
        return "Improving"
    return "Stable"


def build(history_csv, out_dir, iso):
    h = pd.read_csv(history_csv, parse_dates=["date"])
    w = h[(h.level == "admin1") & (h.name != "Nouakchott")].copy()
    piv = w.pivot(index="date", columns="name", values="real_score").sort_index()

    rows = []
    for name in piv.columns:
        s = piv[name].dropna()
        if s.empty:
            continue
        last3 = s.iloc[-1] - s.iloc[max(0, len(s) - 4)]
        rows.append({
            "wilaya": name,
            "first_dekad": s.index[0].date(), "first_score": round(s.iloc[0], 2),
            "latest_dekad": s.index[-1].date(), "latest_score": round(s.iloc[-1], 2),
            "season_change": round(s.iloc[-1] - s.iloc[0], 2),
            "last_3_dekads_change": round(last3, 2),
            "season_trend": label(s.iloc[-1] - s.iloc[0]),
            "recent_trend": label(last3),
            "lowest_score": round(s.min(), 2), "lowest_on": s.idxmin().date(),
            "latest_tier": w[(w.name == name) & (w.date == s.index[-1])]["real_tier"].iloc[0],
        })
    trends = pd.DataFrame(rows).sort_values("latest_score")
    out_dir = Path(out_dir)
    trends.to_csv(out_dir / f"trends_{iso}.csv", index=False)

    # chart
    names = list(trends["wilaya"])
    ncols = 4
    nrows = -(-len(names) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(15, 3.1 * nrows), sharey=True)
    axes = axes.flatten()
    for ax, name in zip(axes, names):
        s = piv[name].dropna()
        ax.plot(s.index, s.values, color=NAVY, lw=2.2, marker="o", ms=4)
        for y, lab, col in TIER_LINES:
            ax.axhline(y, color=col, lw=0.8, ls="--", alpha=0.8)
        ax.set_ylim(0.8, 5)
        tr = trends.set_index("wilaya").loc[name, "recent_trend"]
        ax.set_title(f"{name}  ({tr.lower()})", fontsize=11, fontweight="bold", color=NAVY)
        ax.tick_params(axis="x", labelrotation=45, labelsize=8)
        ax.tick_params(axis="y", labelsize=8)
        ax.grid(alpha=0.25)
    for ax in axes[len(names):]:
        ax.axis("off")
    fig.suptitle("Real Resource Score by dekad, 2026 season (lower = worse; dashed lines are tier boundaries)",
                 fontsize=13, fontweight="bold", color=NAVY, y=1.0)
    fig.text(0.01, -0.01, "Tier boundaries: below 1.75 SEVERE, 1.75-2.75 HIGH, 2.75-3.25 MODERATE-HIGH, 3.25-4.0 MODERATE, above 4.0 FAVORABLE. "
             "Built from backfilled dekad snapshots; see build_trends.py.", fontsize=8, color="#555555")
    plt.tight_layout()
    plt.savefig(out_dir / f"trends_{iso}.png", dpi=150, bbox_inches="tight", facecolor="white")
    return trends


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default="output/history_MRT.csv")
    ap.add_argument("--out-dir", default="output")
    ap.add_argument("--iso", default="MRT")
    a = ap.parse_args()
    t = build(a.history, a.out_dir, a.iso)
    print(t[["wilaya", "first_score", "latest_score", "season_change", "last_3_dekads_change", "season_trend", "recent_trend"]].to_string(index=False))
