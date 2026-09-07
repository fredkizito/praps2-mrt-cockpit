"""
alert_bot.py
============
Watches for state changes between engine runs and generates alerts.

Real-world deployment: this runs after every praps2_engine.py invocation
(triggered by a scheduler once HDX publishes a new dekad - see
config/schedule.md). In this demo it diffs two REAL states already
computed from actual data (21 Jul 2026 vs 21 Aug 2026), so every alert
below is genuine, not simulated.

Senders are pluggable. dry_run() always works (prints to stdout).
send_slack() is real, correct code - point it at a real Incoming Webhook
URL and it sends. No webhook URL is configured in this session, so it's
demonstrated via dry_run() only.
"""

import json
import argparse
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

SEVERE_TIERS = {"SEVERE"}
WATCH_TIERS = {"SEVERE", "HIGH"}


def load_state(path):
    with open(path) as f:
        return json.load(f)


def index_by_key(records, key):
    return {r[key]: r for r in records}


def diff_states(prev, curr, key="wilaya", level="admin1"):
    """Compare two state snapshots and return a list of alert dicts."""
    prev_idx = index_by_key(prev[level], key)
    curr_idx = index_by_key(curr[level], key)
    alerts = []

    for name, cur_rec in curr_idx.items():
        prev_rec = prev_idx.get(name)
        cur_tier = cur_rec.get("real_tier")
        cur_score = cur_rec.get("real_score")

        if prev_rec is None:
            continue
        prev_tier = prev_rec.get("real_tier")
        prev_score = prev_rec.get("real_score")

        # 1. Tier crossed a boundary
        if prev_tier != cur_tier:
            direction = "worsened" if _tier_rank(cur_tier) < _tier_rank(prev_tier) else "improved"
            alerts.append({
                "severity": "high" if cur_tier in SEVERE_TIERS else ("medium" if cur_tier in WATCH_TIERS else "info"),
                "type": "tier_change",
                "unit": name,
                "level": level,
                "message": (f"{name}: risk tier {direction} from {prev_tier} to {cur_tier} "
                            f"(score {prev_score:.2f} -> {cur_score:.2f})"),
            })

        # 2. Now at/below the severe threshold, regardless of prior tier
        if cur_tier == "SEVERE" and prev_tier != "SEVERE":
            alerts.append({
                "severity": "critical",
                "type": "severe_entry",
                "unit": name,
                "level": level,
                "message": f"{name} has entered SEVERE risk (score {cur_score:.2f}) as of {curr['as_of']}.",
            })

        # 3. PSVI crossed into VERY HIGH (admin1 only)
        if level == "admin1":
            prev_psvi = prev_rec.get("psvi_tier")
            cur_psvi = cur_rec.get("psvi_tier")
            if cur_psvi == "VERY HIGH" and prev_psvi != "VERY HIGH":
                alerts.append({
                    "severity": "medium",
                    "type": "psvi_alert",
                    "unit": name,
                    "level": level,
                    "message": f"{name}: livestock-pressure vulnerability (PSVI) entered VERY HIGH "
                               f"({cur_rec.get('psvi')}) - reserve-drawdown risk.",
                })

    return alerts


def _tier_rank(tier):
    order = ["SEVERE", "HIGH", "MODERATE-HIGH", "MODERATE", "FAVOURABLE", "NO DATA", "N/A"]
    return order.index(tier) if tier in order else len(order)


# ---------------------------------------------------------------------------
# Senders
# ---------------------------------------------------------------------------

def dry_run(alerts, as_of):
    print(f"\n=== PRAPS2 ALERT BOT — dekad {as_of} — {len(alerts)} alert(s) ===\n")
    icon = {"critical": "[CRITICAL]", "high": "[HIGH]", "medium": "[WATCH]", "info": "[INFO]"}
    for a in sorted(alerts, key=lambda x: ["critical", "high", "medium", "info"].index(x["severity"])):
        print(f"{icon.get(a['severity'], '[?]')} {a['message']}")
    print()


def send_slack(webhook_url, alerts, as_of):
    """Real Slack Incoming Webhook sender. Requires `requests` and a live
    webhook URL (Slack: Apps -> Incoming Webhooks -> Add to Slack)."""
    if requests is None:
        raise RuntimeError("requests not installed - pip install requests")
    if not alerts:
        text = f"PRAPS2 dekadal check ({as_of}): no threshold changes."
    else:
        lines = [f"*PRAPS2 Pastoral Alert — dekad {as_of}* ({len(alerts)} item(s))"]
        for a in alerts:
            lines.append(f"• {a['message']}")
        text = "\n".join(lines)
    resp = requests.post(webhook_url, json={"text": text}, timeout=10)
    resp.raise_for_status()
    return resp


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prev", required=True)
    parser.add_argument("--curr", required=True)
    parser.add_argument("--slack-webhook", default=None)
    args = parser.parse_args()

    prev = load_state(args.prev)
    curr = load_state(args.curr)

    alerts = diff_states(prev, curr, key="wilaya", level="admin1")
    alerts += diff_states(prev, curr, key="PCODE", level="admin2")

    dry_run(alerts, curr["as_of"])

    if args.slack_webhook:
        send_slack(args.slack_webhook, alerts, curr["as_of"])
        print(f"Sent to Slack.")
    else:
        print("(No --slack-webhook provided; ran in dry-run mode only.)")
