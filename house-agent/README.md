# House Agent

A web app that runs an AI agent on a schedule to find houses for sale that match your
criteria, and keeps the results in a dashboard. It replaces the "Weekly Midwest house
search" routine and its Google Sheet: the same criteria, statuses, Reviewed/Dismissed
workflow and Excluded list, with history kept in a database.

```
frontend/  React + TypeScript + Tailwind dashboard (Vite)
backend/   Python API (FastAPI + SQLite), scheduler, and the Claude search agent
```

## How it works

1. A **guided setup** walks the user through a few questions: home type, price range, size,
   a central address, ZIP code, or landmark with a maximum drive time, how much work
   they'll take on, and how often to search. From the location and drive time, Claude
   suggests the counties to search (`POST /api/wizard/regions`). The user unchecks or adds
   counties, and the answers become a **search profile**.
2. A **search profile** holds the criteria (price, lot size, property type), the anchors
   (e.g. airports plus a maximum drive time), the regions to search (counties, optionally
   with a Redfin county ID), the condition rules, and a weekly schedule.
3. On each run, `agent/runner.py`:
   - **searches** each county, spreading the work across listing sites. It judges listings
     from the results pages, opens the pages of promising candidates (within a page budget
     per county), and labels their condition as `good`, `needs_updating` or `reject`.
     Tracked listings it passes on a results page are reported with their current price and
     status, so they count as checked without opening their pages. Counties that found
     nothing new in their last few searches get a smaller page budget.
   - **status-checks** (with a cheaper model) only the tracked listings the searches didn't
     show and that weren't confirmed in the last few days: a web search for the MLS number
     or address, reading prices and statuses from the result snippets, and opening a saved
     link only when that isn't enough.
   - **re-reads** condition only for listings whose price or status changed, and for ones
     whose condition couldn't be read yet.
   Each listing keeps its MLS number and a link for every site it has been seen on. The main
   link is the working one on the site that blocks the agent least, and it moves when a
   link dies or the listing turns up somewhere more reliable.
4. The agent (`agent/claude_agent.py`) uses Claude with the server-side `web_search` /
   `web_fetch` tools and reports back through a `submit_*` tool with a checked schema.
   It only reports what it saw.
5. `reconcile.py` then decides what changes, in plain code: new listings, price changes,
   removals (sold, pending, off-market, out of criteria, major repairs), relistings. Excluded
   addresses are never added back. Every change is saved as a listing event, so each house
   keeps its history.

| Google Sheet | App |
|---|---|
| Status: New this week / Active / Active - needs updating / Unverified | Status badges and filter chips; "new" means first seen in the latest run |
| Reviewed checkbox | Reviewed toggle on each card and table row |
| Dismissed checkbox, moved to Excluded on the next run | **Rule out** button: moves it to Excluded right away, with a reason; **Restore** undoes it |
| Excluded tab | Excluded page, where you can also add addresses by hand |
| Price-cut notes | Old price shown struck through, plus a price history per listing |
| Friday summary | Runs page: added, removed, price changes, regions it couldn't check, errors, usage |

## Setup

Requirements: Python 3.11+, Node 20+, and an Anthropic API key.

```bash
# Backend
cd house-agent/backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...        # keep this in your shell or a secret store, never in git

# Frontend
cd ../frontend
npm install
```

The first time you open the app it starts the guided setup. Add more searches later with
**New search**.

To move an existing search over from the Google Sheet (an admin step, not something users
do), import a seed file from the command line. `*.local.json` files and `backend/data/` are
gitignored:

```bash
house-agent import path/to/my-search.local.json
```

### Run it

Development (hot reload), in two terminals:

```bash
cd house-agent/backend && house-agent serve          # API on :8000, scheduler on
cd house-agent/frontend && npm run dev               # UI on http://localhost:5173
```

Single process: run `npm run build` in `frontend/`, then `house-agent serve`. The backend
serves the built UI at http://localhost:8000.

Run one search from the terminal (runs in the foreground and prints the summary):

```bash
house-agent run 1
```

## Deploy (Render)

`render.yaml` at the repo root is a Render Blueprint. It uses Render's native Python runtime:
`house-agent/render-build.sh` builds the dashboard and installs the API, and
`house-agent/render-start.sh` starts one server process with the database on a 1 GB disk at
`/data`. (`house-agent/Dockerfile` builds the same app as a container for other hosts; an
existing Render service can't be switched between Docker and a native runtime.)

1. Open https://render.com/deploy?repo=https://github.com/lucastarzwell-netizen/Fun, or in
   the Render dashboard choose **New → Blueprint** and pick this repo. Render reads
   `render.yaml` from the default branch (`main`), so merge this work into `main` first, or
   choose the branch in the Blueprint screen.
2. Render asks for two values:
   - `ANTHROPIC_API_KEY`: your Claude API key (create one at console.anthropic.com).
   - `HOUSE_AGENT_PASSWORD`: the password for the app's sign-in screen. Use a long one.
3. Deploy. The app is then live at `https://house-agent-XXXX.onrender.com`. The first
   visit asks for the password, then starts the guided setup.

It uses Render's Starter plan (about $7/month) plus about $0.25/month for the disk. The
free plan won't work: it sleeps when idle, so scheduled searches wouldn't run, and it has no
disk, so the database would be wiped. Claude API usage is billed separately by Anthropic.

To move your existing Google Sheet search over after deploying, open a Render **Shell** on
the service and run `house-agent import <file>` with your seed file.

### Configuration (environment variables)

| Variable | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required for runs) | |
| `HOUSE_AGENT_MODEL` | `claude-opus-5` | County searches and condition re-reads. Must support the `*_20260209` web tools and adaptive thinking (Opus 4.6+, Sonnet 4.6+) |
| `HOUSE_AGENT_EFFORT` | `medium` | Effort for that model: `low` / `medium` / `high`; lower costs less |
| `HOUSE_AGENT_CHECK_MODEL` | `claude-sonnet-5` | Quick status/price checks. Same tool requirements (not Haiku) |
| `HOUSE_AGENT_CHECK_EFFORT` | `low` | Effort for status checks |
| `HOUSE_AGENT_SEARCH_FETCHES` | `20` | Pages the agent may open per county search |
| `HOUSE_AGENT_QUIET_FETCHES` | `10` | Page budget for counties that found nothing new lately |
| `HOUSE_AGENT_QUIET_AFTER` | `3` | Searches in a row with nothing new before a county counts as quiet (`0` = never) |
| `HOUSE_AGENT_SEARCH_WEB_SEARCHES` | `10` | Web searches per county search |
| `HOUSE_AGENT_RECHECK_DAYS` | `3` | Tracked listings confirmed within this many days aren't checked again |
| `HOUSE_AGENT_RELABEL_LIMIT` | `12` | Most listings re-read for condition per run |
| `HOUSE_AGENT_STATUS_BATCH` / `HOUSE_AGENT_CHECK_BATCH` | `8` / `6` | Listings per status-check / re-read call |
| `HOUSE_AGENT_DATABASE_URL` | `sqlite:///backend/data/house_agent.db` | Any SQLAlchemy URL (e.g. Postgres) |
| `HOUSE_AGENT_SCHEDULER` | `1` | `0` turns off the in-process scheduler |
| `HOUSE_AGENT_CORS_ORIGINS` | Vite dev origins | |
| `HOUSE_AGENT_PASSWORD` | (unset: no sign-in) | Set on any public deployment |
| `HOUSE_AGENT_SECRET` | derived from password | Key that signs session cookies |
| `HOUSE_AGENT_SECURE_COOKIES` | `0` | `1` when served over HTTPS |
| `HOUSE_AGENT_SMTP_USER` | (unset: no email) | Mail account the summaries are sent through |
| `HOUSE_AGENT_SMTP_PASSWORD` | | Its password; for Gmail, an [app password](https://myaccount.google.com/apppasswords) |
| `HOUSE_AGENT_SMTP_HOST` / `_PORT` | `smtp.gmail.com` / `587` | Any SMTP server; port 465 uses SSL |
| `HOUSE_AGENT_EMAIL_FROM` | the SMTP user | "From" address, e.g. an alias. Gmail requires it to be a verified "Send mail as" address |
| `HOUSE_AGENT_EMAIL_NAME` | `House Agent` | Sender name recipients see |
| `HOUSE_AGENT_PUBLIC_URL` | Render's URL | Link to the app in emails |

## Adding logins later

The app runs as a single local user today, but it's built so login can be added later:

- Every search profile has an `owner_id`, and every API route loads data only through the
  current user's profiles (`api/deps.py`).
- `auth.get_current_user` is the one place that decides who the user is. Today it checks
  the optional shared password's session cookie. Replace it with per-user sessions (for
  example an OAuth provider). Nothing else in the API changes.
- The frontend already sends `credentials: "include"` on every request.

## Tests

```bash
cd house-agent/backend && pytest && ruff check src tests
cd house-agent/frontend && npm run typecheck
```

The tests cover address matching, Redfin URL building, reconciliation (new listings, price
changes, removals, exclusions, relistings, partial runs), the API, and the agent loop
against a fake Anthropic client. None of them call the network.

## Known limits

- **Listing data.** Searches are spread across Redfin, Zillow, Realtor.com and Homes.com
  (plus LandWatch for land), configurable in Search settings. Each county leads with a site
  it didn't use last run, so coverage rotates across sites; sites that block the agent are
  tried last next time, and the Runs page shows per-site results. The agent never works
  around a block. None of these sites offer a public API, and their terms don't allow
  scraping. Light personal use is one thing; if other people will use this, switch to a
  licensed listings API before opening it up.
- **Cost.** Most of a run's cost is the county searches. The Runs page shows an estimated
  cost per run, per model and per county (model tokens only; web search and fetch fees are
  extra), which is the place to see what a settings change saves.
- **Drive times** are the model's estimates, as in the sheet.
