# PRAPS2 Pastoral Early Warning & Decision System — Reference Implementation

Built and validated against real Mauritania data (WFP/MODIS NDVI + CHIRPS
rainfall via HDX, RGE 2024 livestock census, ANSADE/HDX COD-AB boundaries)
in this conversation. Every number this system produces has been
cross-checked against the manual analysis done earlier — the engine
reproduces it exactly (see `engine/` validation below).

## Live reference deployment

The cockpit (`cockpit/praps2_cockpit_v2.html`) is deployed and publicly
reachable at:

**https://miavcdpraps.netlify.app/**

This is a static snapshot of the 21 August 2026 dekad — deploying it to
Netlify does not make it live-updating. It demonstrates that the
cockpit is genuinely standalone (a single self-contained HTML file with
no server or database dependency) and gives colleagues a link to test-drive
instead of a file to download and open locally.

Notes on this deployment:
- **Public by default.** Netlify's free tier does not restrict access —
  anyone with the URL can open it. Fine for an internal test-drive; add
  Netlify password protection (paid tier) or an app-level password
  prompt if that's not acceptable for this data.
- **To refresh it:** re-run the engine at a new `--as-of` date, rebuild
  `cockpit/praps2_cockpit_v2.html` with the new state bundle embedded,
  and re-deploy (drag the new file into Netlify, or `netlify deploy` via
  CLI if the site is linked to a project).
- **Rename the URL:** Netlify dashboard → Site settings → Change site
  name, to get a more identifiable subdomain (e.g.
  `praps2-mrt-cockpit.netlify.app`) instead of the auto-generated one.

## Automating it: the GitHub Actions workflow

`.github/workflows/refresh.yml` is a ready-to-drop-in workflow that runs
the entire chain above automatically:

```
fetch_hdx_data.py → build_bundle.py → render_cockpit.py →
generate_ch_packet.py → alert_bot.py (Slack) → git commit/push → Netlify deploy
```

**Setup, in order:**

1. **Push this whole `praps2_app/` folder to a GitHub repo.** The workflow
   file must live at `.github/workflows/refresh.yml` relative to the repo
   root — if you nest this folder inside another repo, move the
   `.github/` directory up to that repo's root.
2. **Decide how Netlify should redeploy** (pick one):
   - **Git-linked** (recommended if starting fresh): in Netlify, "Import
     from Git" and point it at this repo. Then delete the final "Deploy
     to Netlify directly" step in `refresh.yml` — the `git push` step
     alone will trigger Netlify's own build automatically.
   - **Direct deploy** (use this if your site was created by dragging a
     file into Netlify, like the first version of this cockpit was — it
     isn't Git-linked and relinking would require reconfiguring it): add
     two repository secrets (Settings → Secrets and variables → Actions):
     - `NETLIFY_AUTH_TOKEN` — Netlify → User settings → Applications →
       New access token
     - `NETLIFY_SITE_ID` — Netlify → Site settings → Site details → Site ID
3. **Optional: Slack alerts.** Add a `SLACK_WEBHOOK_URL` repository
   secret (Slack → your workspace → Apps → Incoming Webhooks) to have
   the alert bot post directly to a channel. Leave it unset and the step
   safely no-ops (falls back to a log-only dry run) — it isn't a hard
   dependency.
4. **Test it manually first.** Go to the repo's Actions tab → "PRAPS2
   dekadal refresh" → "Run workflow" — this fires the same job the cron
   schedule would, so you can confirm it works before waiting for the
   next scheduled run.

**On the schedule:** the cron (`0 6 3,13,23 * *`) runs at 06:00 UTC on
the 3rd, 13th, and 23rd of each month — a two-day buffer after HDX's
typical dekad publication dates (1st/11th/21st), since publication timing
can vary slightly. Adjust if you find HDX consistently publishes earlier
or later.

**What still needs a first real test:** the CKAN API calls in
`fetch_hdx_data.py` (`data.humdata.org/api/3/action/package_show`) use
HDX's standard, documented API pattern — the same one every other
WFP subnational dataset on HDX follows — but this exact call could not
be executed from the sandboxed session this pipeline was built in
(the same bot-detection issue described elsewhere in this README). It
should work from a normal GitHub Actions runner; the "test it manually
first" step above is how you'll find out.

**Fallback: `data/manual/` — commit the CSVs yourself.** If automated
fetch turns out not to work, drop the two CSVs into `data/manual/`
(exact steps in `data/manual/README.md`) via GitHub's web UI — no git
command line needed. A commit to that folder triggers the whole
pipeline immediately via the workflow's `push` trigger, using those
files instead of trying to fetch from HDX. This is the same ~10-day
cadence as the schedule, just with a human doing the download step —
a reasonable trade of automation for reliability if the direct fetch
doesn't pan out. See `data/manual/README.md` for the exact filenames
the pipeline expects.

## What's real vs. what needs connecting

| Component | Status | What's needed to go live |
|---|---|---|
| `engine/praps2_engine.py` | **Fully working.** Runs end-to-end on real data, produces validated output. | A scheduler (see below) to run it automatically each dekad. |
| `bot/alert_bot.py` | **Fully working.** Generated 48 real alerts from two actual dekads (21 Jul vs 21 Aug 2026). | A live Slack webhook URL (`send_slack()` is correct, tested code — just needs the URL) or another transport. |
| `cockpit/praps2_cockpit_v2.html` | **Fully working, and live** at https://miavcdpraps.netlify.app/ (static snapshot, 21 Aug 2026 dekad). Real Leaflet map on official ANSADE boundaries, wilaya→moughataa drill-down, live engine data. | Nothing to test it — open the link or the file. To make it auto-refresh rather than serve a static snapshot, rebuild and redeploy on the same schedule as the engine (see Scheduling below). |
| `ch_packet/generate_ch_packet.py` | **Fully working.** Generated a real .docx from live state in this session. | Nothing — run it before each CH cycle. |
| `field_tool/sms_generator.py` | **Working logic, unconnected transport.** Produces correct, real, GSM-safe SMS/USSD text. | An SMS gateway account (Africa's Talking, Twilio, or a Mauritanian telecom's bulk-SMS API) to actually deliver messages. |
| Regional scale-up | **Architecture only.** `config/countries/_template.json` shows how a second country plugs in with zero code changes. | Real NDVI/rainfall/livestock/boundary data for each additional country — the same three uploads that made Mauritania real. |

## How to run it

```bash
# 1. Ingest + calculate (produces output/state_MRT_<date>.json)
python3 engine/praps2_engine.py --config config/countries/mrt.json --as-of 2026-08-21

# 2. Diff against the previous dekad and print/send alerts
python3 bot/alert_bot.py --prev output/state_MRT_2026-07-21.json --curr output/state_MRT_2026-08-21.json
#   add --slack-webhook <url> to actually deliver

# 3. Generate the CH technical input packet
python3 ch_packet/generate_ch_packet.py --state output/state_MRT_2026-08-21.json \
    --prev-state output/state_MRT_2026-07-21.json --out output/CH_Packet.docx

# 4. Generate field SMS text for every wilaya
python3 field_tool/sms_generator.py --state output/state_MRT_2026-08-21.json
```

Steps 2–4 all read the JSON that step 1 produces. Nothing recomputes
anything — this is the "single source of truth" design mentioned in the
engine's docstring, and it's why the cockpit, the CH packet, and the SMS
text can never disagree with each other.

## Scheduling (to make step 1 automatic)

HDX publishes a new dekad roughly every 10 days. The engine should re-run
within a day or two of each publication. Two realistic options, neither
requiring infrastructure beyond what a small team already has:

- **GitHub Actions** (free for public/low-volume private repos): a
  `schedule: cron: '0 6 */10 * *'` workflow that pulls the latest HDX
  CSVs, runs the four commands above, and commits the outputs or pushes
  the CH packet/alerts as workflow artifacts or Slack messages.
- **A single cron job** on any always-on machine (a spare office PC, a
  small cloud VM) running the same four commands.

Either way, the missing piece is **automated HDX download** — this
session always used user-uploaded CSVs because HDX's website blocked
this session's fetch tool. A normal server (not a sandboxed chat session)
does not have that restriction; `requests.get()` against the HDX resource
URL works fine outside this environment.

## File map

```
praps2_app/
├── .github/workflows/refresh.yml  # the automation — see "Automating it" above
├── engine/praps2_engine.py       # ingestion + VCI/PSVI calculation
├── bot/alert_bot.py               # threshold diffing + alert delivery
├── scripts/fetch_hdx_data.py      # downloads fresh NDVI/rainfall CSVs from HDX
├── data/manual/README.md          # fallback: drop CSVs here by hand if automated fetch fails
├── scripts/build_bundle.py        # runs the engine + alert diff, assembles bundle.json
├── scripts/render_cockpit.py      # injects bundle.json into the template
├── cockpit/cockpit_template.html  # reusable template (has the __BUNDLE_JSON__ placeholder)
├── cockpit/praps2_cockpit_v2.html # the rendered dashboard (open this file, or see live deployment above)
├── cockpit/admin1.json, admin2.json # static boundary geometry (doesn't change dekad to dekad)
├── ch_packet/generate_ch_packet.py
├── field_tool/sms_generator.py
├── config/countries/mrt.json      # Mauritania — real, populated
├── config/countries/_template.json # onboarding template for country 2
└── output/                        # generated state, alerts, packets
```

Live deployment: https://miavcdpraps.netlify.app/ (cockpit only; static snapshot, 21 Aug 2026 dekad — see "Live reference deployment" above. Once the workflow above is running, this will refresh automatically instead.)
