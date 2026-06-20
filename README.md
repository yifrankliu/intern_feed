# ⚡ Intern Feed

A personal, single-page aggregator for tech-internship postings. It pulls from
community GitHub trackers (breadth) **and** directly from your target companies'
applicant-tracking systems (speed on your shortlist), deduplicates everything,
filters to what's relevant to you, and shows it in one fast, sortable page with
brand-new postings highlighted.

No server and no database. A scheduled GitHub Action re-runs the ingestion and
commits an updated `data/postings.json`; the static `index.html` reads that file.

---

## What it does

- **Two kinds of sources**
  - *Community repos* (breadth): structured `listings.json` where available,
    Markdown-table parsing as a fallback.
  - *Target-company ATS* (speed): Greenhouse / Lever / Ashby public JSON, so you
    catch your shortlist before the community lists do. Workday/custom portals
    are marked **calendar-only** instead of scraped.
- **Normalizes** every posting to one schema, **deduplicates** across sources
  (merging the list of where each posting appeared), and **filters** to SWE / ML
  / quant / hardware, US + Remote, with non-US (incl. Asia/HK) **flagged, not
  dropped**.
- **Highlights** postings that are new since your last visit (tracked in your
  browser's `localStorage`), with free-text search and quick filters.

---

## Project layout

```
intern-feed/
├─ index.html               # the whole site (no build step)
├─ data/
│  ├─ postings.json         # current live feed the site reads (seeded; refreshed by the Action)
│  └─ seen.json             # cumulative archive of every posting ever seen (id-keyed)
├─ config/
│  ├─ repos.json            # community GitHub trackers
│  ├─ companies.json        # target companies + ATS tokens (or calendar-only)
│  └─ filters.json          # categories / region / intern-keyword rules
├─ ingest/
│  ├─ ingest.py             # the pipeline
│  └─ requirements.txt
└─ .github/workflows/
   └─ refresh.yml           # cron that refreshes data/postings.json
```

---

## Run it locally

```bash
cd intern-feed
pip install -r ingest/requirements.txt
python ingest/ingest.py            # writes data/postings.json

# then serve the folder (needed because the page fetches data/postings.json)
python -m http.server 8000
# open http://localhost:8000
```

Opening `index.html` via `file://` will not work in some browsers because of
`fetch()` restrictions — use the local server above.

The repo ships with a **seed** `data/postings.json` (real postings from one of
the community sources) so the page isn't empty before your first run. Running the
ingest replaces it with the full set from every working source.

---

## Deploy (GitHub Pages + Actions cron)

1. Create a GitHub repo and push this folder to the `main` branch.
2. **Settings → Pages →** Source: *Deploy from a branch*, Branch: `main`,
   Folder: `/ (root)`. Your site goes live at
   `https://<you>.github.io/<repo>/`.
3. **Settings → Actions → General →** Workflow permissions: *Read and write*
   (so the bot can commit refreshed data).
4. The workflow in `.github/workflows/refresh.yml` runs four times a day at
   00:00 / 06:00 / 12:00 / 18:00 **New Haven (US Eastern)** time — set in UTC
   for EDT (`0 4,10,16,22 * * *`); in winter (EST) it drifts one hour earlier.
   It also runs on demand from the **Actions** tab. Each run regenerates
   `data/postings.json`
   and commits it only if something changed; Pages re-publishes automatically.

> Prefer Vercel? Import the repo as a static project (no build command, output
> dir = root). Keep the GitHub Action for data refresh — it just commits JSON,
> which Vercel redeploys on push.

---

## Add or remove a source (no code changes)

**A community repo** — edit `config/repos.json`:

```jsonc
{
  "name": "owner/RepoName",        // GitHub owner/repo
  "branch": "dev",                 // branch to read
  "type": "json",                  // "json" or "readme"
  "json_path": ".github/scripts/listings.json",  // for type=json
  // "readme_path": "README.md", "readme_section": "the list",  // for type=readme
  "source_label": "ShortName"      // badge shown in the UI
}
```

> **When SimplifyJobs rolls over to a `Summer2027` repo**, just change that
> entry's `name` (and confirm the `branch`). Everything else stays the same.

**A target company** — edit `config/companies.json`:

```jsonc
{ "name": "Acme",  "ats": "greenhouse", "token": "acmeboard" }
{ "name": "Beta",  "ats": "lever",      "token": "beta" }
{ "name": "Gamma", "ats": "ashby",      "token": "gamma" }
{ "name": "Delta", "ats": "calendar-only", "note": "Workday — track manually" }
```

How to find the `token` (the board slug):

- **Greenhouse** — the company's job board lives at
  `boards.greenhouse.io/<token>` or `job-boards.greenhouse.io/<token>`.
  Verify: `https://boards-api.greenhouse.io/v1/boards/<token>/jobs` returns JSON.
- **Lever** — board at `jobs.lever.co/<token>`. Verify:
  `https://api.lever.co/v0/postings/<token>?mode=json`.
- **Ashby** — board at `jobs.ashbyhq.com/<token>`. Verify:
  `https://api.ashbyhq.com/posting-api/job-board/<token>`.

If a company runs on **Workday or a custom portal**, set
`"ats": "calendar-only"` with a `note` — it'll be listed under *Source coverage*
but not pulled, so you can track it on your own calendar.

**Filters** — edit `config/filters.json`:

```jsonc
{
  "categories": ["swe", "ml", "quant", "hardware"],  // keep only these
  "include_remote": true,
  "include_intl": true,                  // keep non-US roles (flagged, not dropped)
  "require_intern_keyword_for_ats": true,// ATS feeds: keep only intern-looking roles
  "min_posted_date": "2026-05-01",       // drop anything posted before this date
  "drop_unknown_posted_date": false,     // also drop rows with no date? (README rows have none)
  "seen_retention_days": 0               // 0 = keep the archive forever
}
```

`min_posted_date` ignores stale postings from earlier cycles: any posting whose
`posted_date` is before this `YYYY-MM-DD` is dropped entirely (never ingested,
never displayed, and not archived in `seen.json`). Postings with **no** date
(e.g. README-table rows) are kept unless `drop_unknown_posted_date` is `true`.

---

## Resolved target companies (current state)

| Company | ATS | How it's tracked |
|---|---|---|
| Databricks | Greenhouse `databricks` | direct pull |
| Datadog | Greenhouse `datadog` | direct pull |
| Anthropic | Greenhouse `anthropic` | direct pull |
| OpenAI | Ashby `openai` | direct pull |
| Hudson River Trading | Greenhouse `wehrtyou` | direct pull |
| Five Rings | Greenhouse `fiveringsllc` | direct pull |
| Jane Street | Greenhouse `janestreetevents` | direct pull (events board; main internships are on the custom janestreet.com portal) |
| Google, Meta, Microsoft, Google DeepMind, Apple, NVIDIA, PyTorch, Susquehanna (SIG), Two Sigma, Citadel, Citadel Securities, Bloomberg, Salesforce, Rippling | — | **calendar-only** (Workday / custom / own ATS) |

---

## History & the cumulative seen-tracker

Alongside the live `postings.json`, the pipeline maintains `data/seen.json` — a
permanent, id-keyed record of **every posting it has ever seen**. Each run:

- gives every posting a stable `id` = `sha1(normalized_company | normalized_title | apply-URL host)`;
- looks that `id` up in `seen.json`, so `first_seen` is **monotonic** — it never
  resets, even if a posting disappears for a while and later comes back
  (the old "reappears as new" bug is gone);
- marks postings that vanished from all sources as `currently_listed: false`
  (with a `delisted_at` time) instead of forgetting them — so closed roles stay
  archived;
- records `times_seen`, `last_seen`, and a snapshot of each posting (company,
  title, url, category, location, sources).

`postings.json` stays the *current* feed (only live roles, each now also carrying
`first_seen`, `last_seen`, `times_seen`). `seen.json` is the *history* — query it
for trends, or to recover a role that has already closed. Each run reports
`new_this_run`, `reappeared_this_run`, `delisted_this_run`, and `total_ever_seen`.

By default the archive is kept forever (`"seen_retention_days": 0` in
`filters.json`). Set it to a positive number of days to prune entries that have
been delisted longer than that. The GitHub Action commits both `postings.json`
and `seen.json` each run, so the history is versioned in git too.

## A note on honesty / limitations

- **Grad-year filtering is approximate.** These sources rarely encode class year,
  so the "early-career?" flag is inferred from title keywords
  (sophomore / freshman / first-year / etc.). It will miss some and over-flag
  others — uncertain roles are surfaced, not hidden.
- **Calendar-only companies are not scraped.** They appear under *Source
  coverage* so you remember to check them; their postings won't show in the list.
- **One broken source never breaks the build.** Each source is isolated; failures
  are logged in `data/postings.json → sources[]` and shown in the *Source
  coverage* panel.
- Only the public ATS JSON endpoints above are used. **LinkedIn, Indeed,
  Instagram, and Glassdoor are never scraped.**

---

## Optional: email digest (not built yet)

Deferred by design — the core site comes first. When you want it, the shape is:
a small step (in the Action, after ingest) that diffs the new
`postings.json` against the previous commit and, if there are new postings, sends
a digest email with a fixed subject tag like `[INTERN-FEED]` so a Gmail filter
can auto-file it.

Credentials must come from **environment variables / GitHub Actions secrets**
(e.g. `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `DIGEST_TO`) — never hardcoded.
Ask and this can be added.

---

## The unified schema (per posting)

`company`, `role_title`, `location[]`, `posted_date`, `apply_url`, `season`,
`sponsorship`, `category` (swe/ml/quant/hardware/other), `region`
(us/remote/intl/unknown)