#!/usr/bin/env python3
"""
fetch_hdx_data.py
==================
Downloads the latest Mauritania NDVI and rainfall CSVs from HDX.

Uses HDX's CKAN API (package_show) rather than a hardcoded resource URL,
because resource IDs/filenames on HDX can change between dataset updates
(this happened once already during this project - "adm2-full" was renamed
to "subnat-full"). Resolving the current download URL at run time avoids
that fragility.

This is designed to run on a normal GitHub Actions runner, which is NOT
subject to the bot-detection that blocked automated downloads inside the
sandboxed chat session this pipeline was originally built in - a plain
requests.get() from a standard CI environment works fine here.
"""

import sys
import json
import argparse
from pathlib import Path

import requests

CKAN_BASE = "https://data.humdata.org/api/3/action/package_show"

# Some CKAN/Cloudflare-fronted sites reject requests with no User-Agent or a
# generic Python one - a real browser-like UA header is cheap insurance
# against being blocked for looking like a bot, independent of the
# sandboxed-session restriction documented above.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 PRAPS2-MR-pipeline/1.0")
}

DATASETS = {
    "ndvi": {"id": "mrt-ndvi-subnational", "resource_name_contains": "subnat-full"},
    "rainfall": {"id": "mrt-rainfall-subnational", "resource_name_contains": "subnat-full"},
}


def get_resource_url(dataset_id, name_contains):
    resp = requests.get(CKAN_BASE, params={"id": dataset_id}, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"HDX API returned success=false for dataset '{dataset_id}': {data}")
    resources = data["result"]["resources"]
    matches = [r for r in resources if name_contains in r["name"].lower() and r["format"].upper() == "CSV"]
    if not matches:
        available = [r["name"] for r in resources]
        raise RuntimeError(
            f"No resource matching '{name_contains}' found in dataset '{dataset_id}'. "
            f"Available resources: {available}. The dataset's naming convention may have "
            f"changed - update DATASETS in this script to match."
        )
    # Prefer the most recently modified match if there's more than one
    matches.sort(key=lambda r: r.get("last_modified", ""), reverse=True)
    return matches[0]["url"], matches[0]["name"], matches[0].get("last_modified")


def download(url, out_path):
    resp = requests.get(url, headers=HEADERS, timeout=120, stream=True)
    resp.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="data")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    manifest = {}

    for key, cfg in DATASETS.items():
        print(f"Resolving current download URL for '{cfg['id']}'...")
        url, name, last_modified = get_resource_url(cfg["id"], cfg["resource_name_contains"])
        print(f"  -> {name} (last modified: {last_modified})")
        dest = out_dir / f"{key}.csv"
        download(url, dest)
        print(f"  -> saved to {dest} ({dest.stat().st_size:,} bytes)")
        manifest[key] = {"source_name": name, "source_url": url, "last_modified": last_modified, "path": str(dest)}

    with open(out_dir / "fetch_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print("\nDone. Manifest written to", out_dir / "fetch_manifest.json")
