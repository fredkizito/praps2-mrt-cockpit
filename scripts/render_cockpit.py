#!/usr/bin/env python3
"""
render_cockpit.py
===================
Injects cockpit/bundle.json into cockpit/cockpit_template.html to produce
the final, self-contained cockpit/praps2_cockpit_v2.html - the single
file that gets deployed to Netlify.

The template contains the literal placeholder text __BUNDLE_JSON__ in
place of the data object; this script does a straight string substitution,
not templating logic, so it's deliberately simple and has nothing else to
break.
"""

import argparse
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", default="cockpit/cockpit_template.html")
    parser.add_argument("--bundle", default="cockpit/bundle.json")
    parser.add_argument("--out", default="cockpit/praps2_cockpit_v2.html")
    args = parser.parse_args()

    template = Path(args.template).read_text(encoding="utf-8")
    bundle_json = Path(args.bundle).read_text(encoding="utf-8")

    if "__BUNDLE_JSON__" not in template:
        raise SystemExit(
            f"'__BUNDLE_JSON__' placeholder not found in {args.template} - "
            f"has the template been regenerated from a fully-rendered file by mistake?"
        )

    html = template.replace("__BUNDLE_JSON__", bundle_json)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Rendered {args.out} ({len(html):,} chars)")
