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

1. A **search profile** holds the criteria (price, lot size, property type), the anchors
   (e.g. airports plus a maximum drive time), the regions to search (counties, optionally
   with a Redfin county ID), the condition rules, and a weekly schedule.
2. On each run, `agent/runner.py`:
   - **re-checks** every active listing in batches: still for sale? price changed? condition?
   - **searches** each region. The agent opens the Redfin county results page (built from
     the criteria, same URL pattern as the routine), opens each new candidate's listing,
     and labels its condition as `good`, `needs_updating` or `reject`.
3. The agent (`agent/claude_agent.py`) uses Claude with the server-side `web_search` /
   `web_fetch` tools and reports back through a `submit_*` tool with a checked schema.
   It only reports what it saw.
4. `reconcile.py` then decides what changes, in plain code: new listings, price changes,
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

Import a search profile. `seed.example.json` is a small example; your real search, with its
current listings and Excluded list, can be imported the same way from a local seed file
(`*.local.json` files and `backend/data/` are gitignored):

```bash
cd house-agent/backend
house-agent import seed.example.json
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

### Configuration (environment variables)

| Variable | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required for runs) | |
| `HOUSE_AGENT_MODEL` | `claude-opus-5` | Must support the `*_20260209` web tools and adaptive thinking (Opus 4.6+, Sonnet 4.6+) |
| `HOUSE_AGENT_EFFORT` | `high` | `low` / `medium` / `high`; lower costs less |
| `HOUSE_AGENT_CHECK_BATCH` | `6` | Listings re-checked per model call |
| `HOUSE_AGENT_DATABASE_URL` | `sqlite:///backend/data/house_agent.db` | Any SQLAlchemy URL (e.g. Postgres) |
| `HOUSE_AGENT_SCHEDULER` | `1` | `0` turns off the in-process scheduler |
| `HOUSE_AGENT_CORS_ORIGINS` | Vite dev origins | |

## Adding logins later

The app runs as a single local user today, but it's built so login can be added later:

- Every search profile has an `owner_id`, and every API route loads data only through the
  current user's profiles (`api/deps.py`).
- `auth.get_current_user` is the one place that decides who the user is. Replace it with
  session-cookie or token validation (for example an OAuth provider) and add a `/login`
  route. Nothing else in the API changes.
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

- **Listing data.** Redfin has no public API, and its terms don't allow scraping. Reading a
  handful of pages for your own search, as the weekly routine does, is fine for personal
  use. If other people will use this, switch to a licensed listings API before opening it up.
- **Cost.** A full run is roughly 30 region searches plus re-checks of every tracked house,
  so expect several dollars per run on Opus. Lower `HOUSE_AGENT_EFFORT` or use a Sonnet
  model to cut that; the Runs page shows token and fetch counts for each run.
- **Drive times** are the model's estimates, as in the sheet.
