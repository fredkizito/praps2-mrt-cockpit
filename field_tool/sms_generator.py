"""
sms_generator.py
=================
Generates short, feature-phone-compatible text messages (<=160 chars, French,
since that's the operational language for Mauritania's extension network)
from the engine's current state. This is the field tool: no smartphone or
data connection required, only SMS/USSD, which is why message length and
plain text matter as hard constraints, not style choices.

Real-world deployment: wire send_via_gateway() to an SMS aggregator API
(e.g. Africa's Talking, Twilio, or Mauritel/Mattel's own bulk-SMS product)
and trigger it from alert_bot.py whenever a wilaya a subscriber has
registered for crosses a threshold. Inbound "STATUS <code>" queries would
route to build_sms() and reply automatically - the two-way logic is written
here; only the telecom transport is unconnected in this session.
"""

import json
import argparse
import unicodedata

TIER_FR = {
    "SEVERE": "GRAVE", "HIGH": "ELEVE", "MODERATE-HIGH": "MOYEN-ELEVE",
    "MODERATE": "MOYEN", "FAVOURABLE": "BON", "NO DATA": "PAS DE DONNEES",
}

ACTION_FR = {
    "SEVERE": "Deplacez les troupeaux si possible. Aide alimentaire disponible - contactez l'agent local.",
    "HIGH": "Surveillez l'etat du betail. Reserves de secours recommandees.",
    "MODERATE-HIGH": "Situation a suivre. Pas d'action urgente.",
    "MODERATE": "Conditions moyennes. Suivi normal.",
    "FAVOURABLE": "Bonnes conditions. Zone favorable pour transhumance.",
    "NO DATA": "Donnees non disponibles pour cette zone. Contactez l'agent regional.",
}


def strip_accents(s):
    """Most feature phones/SMS gateways in the Sahel render GSM 7-bit best
    without accented characters - strip them for maximum compatibility."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def build_sms(unit_name, tier, score, as_of, ascii_only=True):
    tier_label = TIER_FR.get(tier, tier)
    action = ACTION_FR.get(tier, "")
    msg = f"PRAPS2 {unit_name}: risque {tier_label} (indice {score:.1f}) au {as_of}. {action}"
    if ascii_only:
        msg = strip_accents(msg)
    if len(msg) > 160:
        msg = msg[:157] + "..."
    return msg


def build_ussd_menu(state):
    """A *USSD*-style menu tree (feature-phone interactive session, e.g.
    dial *789# then select a wilaya by number) - richer than one-way SMS,
    still zero-data. Returns the menu as a dict of screens for a USSD
    gateway (Africa's Talking USSD API shape) to serve."""
    wilayas = sorted(state["admin1"], key=lambda d: d["wilaya"])
    menu = {"CON Bienvenue PRAPS2. Choisissez votre wilaya:": {}}
    lines = ["CON Bienvenue PRAPS2. Choisissez votre wilaya:"]
    for i, d in enumerate(wilayas, start=1):
        lines.append(f"{i}. {d['wilaya']}")
    screens = {"root": "\n".join(lines)}
    for i, d in enumerate(wilayas, start=1):
        tier = d["real_tier"]
        screens[str(i)] = (f"END {d['wilaya']}: risque {TIER_FR.get(tier, tier)}. "
                            f"{ACTION_FR.get(tier, '')}")
    return screens


def generate_all_sms(state, ascii_only=True):
    out = []
    for d in state["admin1"]:
        if d["wilaya"] == "Nouakchott":
            continue
        out.append({
            "wilaya": d["wilaya"],
            "tier": d["real_tier"],
            "sms": build_sms(d["wilaya"], d["real_tier"], d["real_score"] or 0, state["as_of"], ascii_only),
        })
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--wilaya", default=None, help="Generate for one wilaya only")
    args = parser.parse_args()

    with open(args.state) as f:
        state = json.load(f)

    if args.wilaya:
        d = next((x for x in state["admin1"] if x["wilaya"] == args.wilaya), None)
        if not d:
            print(f"Wilaya '{args.wilaya}' not found.")
        else:
            sms = build_sms(d["wilaya"], d["real_tier"], d["real_score"] or 0, state["as_of"])
            print(f"[{len(sms)} chars] {sms}")
    else:
        for entry in generate_all_sms(state):
            print(f"[{len(entry['sms']):3d} chars] {entry['wilaya']:20s} {entry['sms']}")

        print("\n--- USSD menu (root screen) ---")
        menu = build_ussd_menu(state)
        print(menu["root"])
