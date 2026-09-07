# Manual data drop — how to refresh without waiting for automated fetch

If `scripts/fetch_hdx_data.py` isn't working (untested from the sandboxed
session this pipeline was built in — see the main README), this folder is
the fallback: drop two files here, in the browser, no git command line
needed, and the whole pipeline runs automatically.

## Steps

1. Go to **https://data.humdata.org/dataset/mrt-ndvi-subnational** and
   download the **`mrt-ndvi-subnat-full.csv`** resource (the *full*
   history, not the "5ytd" 5-year one — the engine needs the full
   2002-present record to compute the 24-year historical envelope).
2. Go to **https://data.humdata.org/dataset/mrt-rainfall-subnational**
   and download **`mrt-rainfall-subnat-full.csv`** the same way.
3. On this repo's GitHub page, navigate into `data/manual/`, click
   **Add file → Upload files**, and drag in both CSVs.
4. **Rename them to exactly `ndvi.csv` and `rainfall.csv`** before
   committing (click the filename in the upload box to rename it — the
   pipeline looks for these exact names, not HDX's original filenames).
5. Commit directly to `main`.

That commit automatically triggers the `PRAPS2 dekadal refresh` workflow
(see `.github/workflows/refresh.yml` — it watches this exact folder) —
you don't need to also run it manually or wait for the schedule. Check
the repo's **Actions** tab to watch it run; it takes a couple of minutes.

## What happens next

The workflow uses whatever is in this folder *instead of* trying to
fetch from HDX automatically — see the "Use manual CSVs if present"
step in `refresh.yml`. It does not delete these files afterward, so the
next time you repeat this (roughly every 10 days, whenever HDX publishes
a new dekad), just overwrite the same two files the same way — no need
to remove the old ones first.

## Reminder: HDX publishes on a dekad schedule

New data typically lands around the 1st, 11th, and 21st of each month.
There's no harm in checking a day or two after those dates if you're
not sure whether the latest dekad is out yet — the engine will simply
report the same `content_hash` as last time if nothing's changed, and
the workflow skips the commit/deploy/alert steps in that case.
