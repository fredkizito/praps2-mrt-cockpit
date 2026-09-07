"""
generate_ch_packet.py
======================
Auto-generates the Cadre Harmonise technical-input packet from the engine's
current state - the same crosswalk table and evidence this diagnostic built
by hand in the Technical Annex, now regenerated from live data on demand.

Usage:
    python3 generate_ch_packet.py --state ../output/state_MRT_latest.json \
        --alerts-prev ../output/state_MRT_2026-07-21.json \
        --out ../output/CH_Packet_MRT_2026-08-21.docx

Real-world deployment: run this automatically ~2 weeks before each CH cycle
(the pastoral working-group panel meets ahead of the Oct/Mar analyses), and
email/upload the output to CSA/OSA.
"""

import json
import argparse
from datetime import datetime

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

NAVY = RGBColor(0x1F, 0x38, 0x64)
RED = "B23A32"
ORANGE = "E07B2A"
AMBER = "E8A83A"
YELLOW = "E5C93E"
GREEN = "5B9A48"

TIER_COLOR = {"SEVERE": RED, "HIGH": ORANGE, "MODERATE-HIGH": AMBER, "MODERATE": YELLOW, "FAVOURABLE": GREEN}


def shade_cell(cell, hex_color):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = NAVY
    return h


def build_packet(state, prev_state, out_path):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    title = doc.add_heading("Cadre Harmonise — Technical Input Packet", level=0)
    for run in title.runs:
        run.font.color.rgb = NAVY

    p = doc.add_paragraph()
    p.add_run(f"{state['country']} · PRAPS2-MR pastoral early-warning system\n").bold = True
    p.add_run(f"Auto-generated {state['generated_at']} from dekad {state['as_of']} "
               f"(content hash {state['content_hash']})\n")
    p.add_run("For submission to CSA/OSA ahead of the CH pastoral livelihood-zone panel.").italic = True

    add_heading(doc, "1. National Summary", level=1)
    n_severe = sum(1 for d in state["admin1"] if d["real_tier"] == "SEVERE")
    n_high = sum(1 for d in state["admin1"] if d["real_tier"] == "HIGH")
    n_data = state["n_admin2_with_data"]
    n_total = state["n_admin2_total"]
    doc.add_paragraph(
        f"As of {state['as_of']}, {n_severe} wilaya(s) are classified SEVERE and {n_high} HIGH on real "
        f"Vegetation Condition Index and CHIRPS rainfall data (WFP/MODIS, via HDX). Moughataa-level "
        f"coverage: {n_data} of {n_total} official administrative units have live dekadal data; the "
        f"remainder fall back to their parent wilaya's classification."
    )

    add_heading(doc, "2. Wilaya-Level Risk Tiers (Hazard Contributing Factor)", level=1)
    table = doc.add_table(rows=1, cols=5)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    for i, h in enumerate(["Wilaya", "Real Resource Score", "Tier", "Season-avg VCI", "3-mo Rainfall (% normal)"]):
        hdr[i].text = h
        hdr[i].paragraphs[0].runs[0].bold = True

    for d in sorted(state["admin1"], key=lambda x: x["real_score"] or 0):
        row = table.add_row().cells
        row[0].text = d["wilaya"]
        row[1].text = f"{d['real_score']:.2f}" if d["real_score"] is not None else "n/a"
        row[2].text = d["real_tier"]
        shade_cell(row[2], TIER_COLOR.get(d["real_tier"], "FFFFFF"))
        row[3].text = f"{d['vci_season_avg']:.1f}" if d.get("vci_season_avg") is not None else "n/a"
        row[4].text = f"{d['rain3mo']:.1f}%" if d.get("rain3mo") is not None else "n/a"

    add_heading(doc, "3. Vulnerability Contributing Factor — Pastoral Suitability/Vulnerability Index", level=1)
    doc.add_paragraph(
        "PSVI = livestock density (TLU/km2, RGE 2024) divided by the real resource score. High PSVI flags "
        "wilayas where livestock pressure is large relative to locally available pasture/water, independent "
        "of the hazard rating alone."
    )
    table2 = doc.add_table(rows=1, cols=3)
    table2.style = "Light Grid Accent 1"
    hdr2 = table2.rows[0].cells
    for i, h in enumerate(["Wilaya", "PSVI", "Vulnerability Tier"]):
        hdr2[i].text = h
        hdr2[i].paragraphs[0].runs[0].bold = True
    ranked = sorted([d for d in state["admin1"] if d.get("psvi") is not None],
                     key=lambda x: x["psvi"], reverse=True)
    for d in ranked:
        row = table2.add_row().cells
        row[0].text = d["wilaya"]
        row[1].text = f"{d['psvi']:.2f}"
        row[2].text = d.get("psvi_tier", "")

    add_heading(doc, "4. Dekad-on-Dekad Change Log (Forward-Looking Signal)", level=1)
    if prev_state:
        import sys
        sys.path.insert(0, "../bot")
        from alert_bot import diff_states
        alerts = diff_states(prev_state, state, key="wilaya", level="admin1")
        if alerts:
            for a in alerts:
                doc.add_paragraph(a["message"], style="List Bullet")
        else:
            doc.add_paragraph("No wilaya-level tier changes since the previous dekad.")
    else:
        doc.add_paragraph("No prior-dekad state supplied — change log unavailable for this run.")

    add_heading(doc, "5. Indicator Crosswalk to CH Pillars", level=1)
    table3 = doc.add_table(rows=1, cols=3)
    table3.style = "Light Grid Accent 1"
    hdr3 = table3.rows[0].cells
    for i, h in enumerate(["Indicator", "CH Pillar / Contributing Factor", "Use"]):
        hdr3[i].text = h
        hdr3[i].paragraphs[0].runs[0].bold = True
    crosswalk = [
        ("Real VCI / NDVI anomaly", "Hazard (rainfall/vegetation deficit)", "Hazard-severity input to the pastoral panel"),
        ("Real PSVI", "Vulnerability (structural exposure)", "Flags wilayas where pressure outpaces resources"),
        ("Dekad-on-dekad change log", "Hazard, forward-looking", "Feeds the PROJECTED phase discussion"),
    ]
    for row_data in crosswalk:
        row = table3.add_row().cells
        for i, v in enumerate(row_data):
            row[i].text = v

    footer = doc.add_paragraph()
    footer.add_run(
        "\nSource: HDX 'Mauritania: NDVI/Rainfall at Subnational Level' (WFP/MODIS/CHIRPS); RGE 2024 "
        "(Ministere de l'Elevage) for livestock; ANSADE/HDX COD-AB for administrative boundaries. "
        "Generated by generate_ch_packet.py, part of the PRAPS2 pastoral early-warning pipeline."
    ).italic = True

    doc.save(out_path)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--prev-state", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.state) as f:
        state = json.load(f)
    prev_state = None
    if args.prev_state:
        with open(args.prev_state) as f:
            prev_state = json.load(f)

    path = build_packet(state, prev_state, args.out)
    print(f"CH packet written: {path}")
