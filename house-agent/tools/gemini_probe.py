"""Probe how Gemini's URL context tool handles the pages House Agent reads.

A standalone experiment: it changes nothing in the app. It asks Gemini to read real listing
pages and county results pages, and to find listings on its own with Google Search, then
compares what Gemini reports with what the app knows and writes a report.

Questions it answers:
  1. Can Gemini read each listing site's pages (per-site success rate, retrieval statuses)?
  2. Is what it reads current? The URL context tool reads from Google's index cache first and
     only fetches live when a page isn't cached, so prices and statuses may be stale.
  3. Can it read filtered results pages, the kind the app builds for each county?
  4. Left to search on its own, which pages does it open?
  5. What does it cost in tokens per page and per task?

Truth data, most current first:
  --app URL      the running app, signed in with HOUSE_AGENT_PASSWORD (the demo password
                 is enough: read-only; the searches to probe must be visible to the demo).
  --db           the app's own database. Run it this way on the Render server, where
                 GEMINI_API_KEY and the database already are (Render dashboard > Shell).
  --snapshot F   a saved search file (backend/data/*.local.json), older.

Needs GEMINI_API_KEY and `pip install google-genai` (not an app dependency). Run from
house-agent/backend:
  python ../tools/gemini_probe.py --snapshot data/my-search.local.json --listings 12 --counties 4
Writes data/probe/<timestamp>/report.md and raw.json (data/ is gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import httpx
from google import genai
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))
from house_agent.agent.sources import SITES, site_for_url  # noqa: E402
from house_agent.schemas import Criteria  # noqa: E402

LISTING_PROMPT = """Open this listing page and report what it shows: {url}

Use only what the page says. Reply with one JSON object and nothing else:
{{"read_ok": true/false (false if the page didn't load or showed no listing),
  "address": str, "status": "active" | "pending" | "contingent" | "sold" | "off_market" | "unknown",
  "price": number or null, "beds": number or null, "baths": number or null,
  "acres": number or null, "mls_number": str or null, "days_on_market": number or null,
  "page_dates": "any 'listed', 'updated' or 'sold on' dates shown, verbatim",
  "notes": "anything that suggests the page is out of date, or why it couldn't be read"}}"""

RESULTS_PROMPT = """Open this search results page and list the homes it shows: {url}

Use only what the page says. Reply with one JSON object and nothing else:
{{"read_ok": true/false, "result_count_shown": number or null,
  "filters_applied": "which filters the page shows as active (price, lot size, type), verbatim",
  "listings": [{{"address": str, "city": str, "price": number or null,
                "status": str, "url": str or null}}]  (up to 40),
  "notes": "anything odd: blocked, sign-in wall, captcha, empty, unfiltered"}}"""

DISCOVER_PROMPT = """Find single-family houses currently for sale in {county}, {state} matching:
price {price}, lot at least {acres} acres. Search the web and read listing sites' pages
(Redfin, Zillow, Realtor.com, Homes.com) to build the list; prefer results pages filtered
to these criteria.

Reply with one JSON object and nothing else:
{{"listings": [{{"address": str, "city": str, "price": number or null,
                "status": str, "url": str}}],
  "pages_read": [urls you opened], "notes": str}}"""


def parse_json(text: str) -> dict | None:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            return None
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def addr_key(address: str | None) -> str:
    a = (address or "").lower().split(",")[0]
    a = re.sub(r"[^a-z0-9 ]", " ", a)
    subs = {
        "road": "rd",
        "street": "st",
        "avenue": "ave",
        "drive": "dr",
        "lane": "ln",
        "court": "ct",
        "highway": "hwy",
        "north": "n",
        "south": "s",
        "east": "e",
        "west": "w",
    }
    return " ".join(subs.get(w, w) for w in a.split())


class Probe:
    def __init__(self, model: str, price_in: float | None, price_out: float | None):
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model = model
        self.price_in = price_in
        self.price_out = price_out

    def ask(self, prompt: str, search: bool = False) -> dict:
        tools = [types.Tool(url_context=types.UrlContext())]
        if search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))
        started = time.monotonic()
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(tools=tools),
            )
        except Exception as e:  # noqa: BLE001 - an experiment: record and move on
            return {"error": f"{type(e).__name__}: {e}", "seconds": time.monotonic() - started}
        cand = resp.candidates[0] if resp.candidates else None
        fetched = []
        meta = getattr(cand, "url_context_metadata", None)
        for m in getattr(meta, "url_metadata", None) or []:
            fetched.append({"url": m.retrieved_url, "status": str(m.url_retrieval_status)})
        queries = []
        gm = getattr(cand, "grounding_metadata", None)
        if gm is not None:
            queries = list(getattr(gm, "web_search_queries", None) or [])
        u = resp.usage_metadata
        usage = {
            "prompt": u.prompt_token_count or 0,
            "tool_prompt": getattr(u, "tool_use_prompt_token_count", 0) or 0,
            "thoughts": getattr(u, "thoughts_token_count", 0) or 0,
            "output": u.candidates_token_count or 0,
        }
        return {
            "text": resp.text,
            "data": parse_json(resp.text or ""),
            "fetched": fetched,
            "queries": queries,
            "usage": usage,
            "cost": self.cost(usage),
            "seconds": round(time.monotonic() - started, 1),
        }

    def cost(self, usage: dict) -> float | None:
        if self.price_in is None or self.price_out is None:
            return None
        tokens_in = usage["prompt"] + usage["tool_prompt"]
        tokens_out = usage["output"] + usage["thoughts"]
        return (tokens_in * self.price_in + tokens_out * self.price_out) / 1_000_000


def _truth_from_db(profile_filter: str | None) -> tuple[Criteria, list[dict]]:
    """Read the app's own database (on the Render server: its configured database)."""
    from house_agent.db import SessionLocal
    from house_agent.models import Listing, SearchProfile
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    with SessionLocal() as session:
        profiles = list(session.scalars(select(SearchProfile).order_by(SearchProfile.id)))
        if profile_filter:
            profiles = [p for p in profiles if profile_filter.lower() in p.name.lower()]
        if not profiles:
            sys.exit("No matching search in the database.")
        profile = profiles[0]
        rows = session.scalars(
            select(Listing)
            .where(Listing.profile_id == profile.id, Listing.url.is_not(None))
            .options(selectinload(Listing.sources))
        ).all()
        listings = [
            {
                "address": r.address,
                "city": r.city,
                "state": r.state,
                "url": r.url,
                "price": r.price,
                "mls": r.mls_number,
                "state_in_app": r.listing_state,
                "market_status": r.market_status,
                "as_of": str(r.last_checked or r.first_seen),
                "urls": [r.url] + [s.url for s in r.sources if not s.dead and s.url != r.url],
            }
            for r in rows
        ]
        print(f"Truth: database search '{profile.name}', {len(listings)} listings")
        return Criteria.model_validate(profile.criteria), listings


def load_truth(args) -> tuple[Criteria, list[dict]]:
    """Criteria and listings (with the date the app last confirmed each one)."""
    if args.db:
        return _truth_from_db(args.profile)
    if args.app:
        password = os.environ.get("HOUSE_AGENT_PASSWORD", "")
        with httpx.Client(base_url=args.app.rstrip("/"), timeout=60) as http:
            http.post("/api/auth/login", json={"password": password}).raise_for_status()
            profiles = http.get("/api/profiles").raise_for_status().json()
            if args.profile:
                profiles = [p for p in profiles if args.profile.lower() in p["name"].lower()]
            if not profiles:
                sys.exit("No matching search visible to this login.")
            profile = profiles[0]
            rows = (
                http.get(f"/api/profiles/{profile['id']}/listings", params={"state": "all"})
                .raise_for_status()
                .json()
            )
        print(f"Truth: app search '{profile['name']}', {len(rows)} listings")
        listings = [
            {
                "address": r["address"],
                "city": r["city"],
                "state": r["state"],
                "url": r["url"],
                "price": r["price"],
                "mls": r.get("mls_number"),
                "state_in_app": r["listing_state"],
                "market_status": r.get("market_status"),
                "as_of": r.get("last_checked") or r["first_seen"],
                "urls": [r["url"]] + [s["url"] for s in r.get("also_on") or []],
            }
            for r in rows
            if r.get("url")
        ]
        return Criteria.model_validate(profile["criteria"]), listings
    data = json.loads(Path(args.snapshot).read_text())
    criteria = Criteria.model_validate(data["profile"]["criteria"])
    listings = [
        {
            "address": r["address"],
            "city": r.get("city"),
            "state": r.get("state"),
            "url": r.get("link"),
            "price": r.get("price"),
            "mls": None,
            "state_in_app": "active",
            "market_status": (r.get("status") or "").lower(),
            "as_of": r.get("last_checked") or r.get("first_seen"),
            "urls": [r.get("link")],
        }
        for r in data["listings"]
        if r.get("link")
    ]
    print(f"Truth: snapshot {args.snapshot}, {len(listings)} listings (may be weeks old)")
    return criteria, listings


def pick_listings(listings: list[dict], n: int) -> list[tuple[dict, str]]:
    """Spread across sites: (listing, url) pairs, every known URL of a listing counts."""
    by_site: dict[str, list] = defaultdict(list)
    for li in listings:
        for url in li["urls"]:
            if url:
                by_site[site_for_url(url)].append((li, url))
    picked, i = [], 0
    while len(picked) < n and any(by_site.values()):
        for site in sorted(by_site):
            if by_site[site] and len(picked) < n:
                picked.append(by_site[site].pop(i % len(by_site[site])))
        i += 1
    return picked


def run(args) -> None:
    criteria, listings = load_truth(args)
    probe = Probe(args.model, args.price_in, args.price_out)
    out_dir = Path(args.out) / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    raw: dict = {"model": args.model, "listing_reads": [], "results_reads": [], "discover": []}
    by_key = {addr_key(li["address"]): li for li in listings}

    # 1-2. Listing pages: readable? current?
    for li, url in pick_listings(listings, args.listings):
        print(f"listing  {site_for_url(url):9} {li['address']}")
        r = probe.ask(LISTING_PROMPT.format(url=url))
        r.update(site=site_for_url(url), url=url, truth=li)
        raw["listing_reads"].append(r)

    # 3. County results pages the app would open.
    regions = criteria.regions[: args.counties]
    for region in regions:
        for key in args.sites.split(","):
            site = SITES.get(key)
            url = site.county_url(region, criteria) if site else None
            if not url:
                continue
            print(f"results  {key:9} {region.name}, {region.state}")
            r = probe.ask(RESULTS_PROMPT.format(url=url))
            r.update(site=key, url=url, county=f"{region.name}, {region.state}")
            raw["results_reads"].append(r)

    # 4. Left to search on its own.
    price = f"${criteria.min_price or 0:,}-${criteria.max_price:,}" if criteria.max_price else "any"
    for region in regions[: args.discover]:
        print(f"discover {region.name}, {region.state}")
        r = probe.ask(
            DISCOVER_PROMPT.format(
                county=region.name,
                state=region.state,
                price=price,
                acres=criteria.min_acres or 0,
            ),
            search=True,
        )
        r.update(county=f"{region.name}, {region.state}")
        raw["discover"].append(r)

    (out_dir / "raw.json").write_text(json.dumps(raw, indent=2, default=str))
    report = build_report(raw, by_key)
    (out_dir / "report.md").write_text(report)
    print("\n" + report)
    print(f"Wrote {out_dir}/report.md")


def _status_ok(fetched: list[dict]) -> bool:
    return any("SUCCESS" in f["status"] for f in fetched)


def _tokens(r: dict) -> int:
    u = r.get("usage") or {}
    return sum(u.values())


def build_report(raw: dict, by_key: dict) -> str:
    lines = [f"# Gemini URL context probe: {raw['model']}", ""]

    # Per-site reading.
    per_site: dict[str, Counter] = defaultdict(Counter)
    for r in raw["listing_reads"] + raw["results_reads"]:
        c = per_site[r["site"]]
        c["tries"] += 1
        c["ok"] += bool(r.get("data") and r["data"].get("read_ok"))
        c["fetched_ok"] += _status_ok(r.get("fetched") or [])
        c["tokens"] += _tokens(r)
        for f in r.get("fetched") or []:
            c[f["status"]] += 1
    lines += [
        "## Reading by site",
        "",
        "| Site | Tries | Read OK | Fetch success | Avg tokens | Retrieval statuses |",
        "|---|---|---|---|---|---|",
    ]
    for site, c in sorted(per_site.items()):
        statuses = ", ".join(
            f"{k.split('.')[-1]} {v}" for k, v in c.items() if k.startswith("URL") or "." in k
        )
        lines.append(
            f"| {site} | {c['tries']} | {c['ok']} | {c['fetched_ok']} | "
            f"{c['tokens'] // max(c['tries'], 1):,} | {statuses} |"
        )

    # Freshness on listing pages.
    lines += [
        "",
        "## Listing pages: Gemini vs the app",
        "",
        "| Site | Address | App (as of) | Gemini | Verdict |",
        "|---|---|---|---|---|",
    ]
    verdicts = Counter()
    for r in raw["listing_reads"]:
        t, d = r["truth"], r.get("data") or {}
        app = (
            f"{t.get('market_status') or t['state_in_app']} ${t['price'] or 0:,.0f} ({t['as_of']})"
        )
        if r.get("error") or not d.get("read_ok"):
            gem, verdict = (r.get("error") or d.get("notes") or "no read")[:60], "unreadable"
        else:
            gem = f"{d.get('status')} ${d.get('price') or 0:,.0f}"
            same_price = d.get("price") and t["price"] and abs(d["price"] - t["price"]) < 1
            if t["state_in_app"] == "removed" and d.get("status") == "active":
                verdict = "STALE? app says gone"
            elif same_price:
                verdict = "matches"
            else:
                verdict = "differs"
        verdicts[verdict] += 1
        lines.append(f"| {r['site']} | {t['address']} | {app} | {gem} | {verdict} |")
    lines += [
        "",
        "Verdicts: " + ", ".join(f"{k} {v}" for k, v in verdicts.items()),
        "",
        "\"differs\" isn't necessarily stale: the app's value is as of the date shown. "
        "Check page_dates in raw.json for those rows.",
    ]

    # Results pages.
    lines += [
        "",
        "## County results pages",
        "",
        "| Site | County | Read | Listings shown | Tracked listings among them | "
        "Shown but gone in app | Tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in raw["results_reads"]:
        d = r.get("data") or {}
        shown = d.get("listings") or []
        known = [by_key.get(addr_key(x.get("address"))) for x in shown]
        known = [k for k in known if k]
        gone = [k for k in known if k["state_in_app"] == "removed"]
        lines.append(
            f"| {r['site']} | {r['county']} | {'yes' if d.get('read_ok') else 'no'} | "
            f"{len(shown)} | {len(known)} | {len(gone)} | {_tokens(r):,} |"
        )

    # Discovery.
    lines += ["", "## Searching on its own", ""]
    for r in raw["discover"]:
        d = r.get("data") or {}
        opened = r.get("fetched") or []
        lines += [
            f"### {r['county']}",
            f"- Searches: {'; '.join(r.get('queries') or []) or 'none reported'}",
            f"- Pages opened by the tool: {len(opened)} "
            f"({sum(_status_ok([f]) for f in opened)} succeeded)",
            *[f"  - {f['status'].split('.')[-1]}: {f['url']}" for f in opened[:15]],
            f"- Listings reported: {len(d.get('listings') or [])}, of which tracked by the app: "
            f"{sum(1 for x in d.get('listings') or [] if addr_key(x.get('address')) in by_key)}",
            f"- Tokens: {_tokens(r):,}, {r.get('seconds')}s",
            "",
        ]

    total = sum(_tokens(r) for k in ("listing_reads", "results_reads", "discover") for r in raw[k])
    costs = [r.get("cost") for k in ("listing_reads", "results_reads", "discover") for r in raw[k]]
    lines += ["## Totals", "", f"- Tokens: {total:,}"]
    if all(c is not None for c in costs):
        lines.append(f"- Est. cost: ${sum(costs):.2f}")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--app", help="app URL, e.g. https://house-agent-xxxx.onrender.com")
    src.add_argument("--snapshot", help="saved search JSON")
    src.add_argument("--db", action="store_true", help="the app's own database (on Render)")
    p.add_argument("--out", default="data/probe", help="where to write the report")
    p.add_argument("--profile", help="part of the search name to probe (with --app)")
    p.add_argument(
        "--model",
        default=os.environ.get("GEMINI_MODEL"),
        help="Gemini model id (default $GEMINI_MODEL; --list-models to see them)",
    )
    p.add_argument("--list-models", action="store_true")
    p.add_argument("--listings", type=int, default=12, help="listing pages to read")
    p.add_argument("--counties", type=int, default=3, help="counties for results pages")
    p.add_argument("--sites", default="redfin,zillow,realtor,homes")
    p.add_argument("--discover", type=int, default=2, help="counties to search on its own")
    p.add_argument("--price-in", type=float, help="$ per million input tokens")
    p.add_argument("--price-out", type=float, help="$ per million output tokens")
    args = p.parse_args()
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Set GEMINI_API_KEY.")
    if args.list_models:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        for m in client.models.list():
            if "generateContent" in (m.supported_actions or []):
                print(m.name.removeprefix("models/"))
        return
    if not args.model:
        sys.exit("Pick a model with --model (see --list-models).")
    run(args)


if __name__ == "__main__":
    main()
