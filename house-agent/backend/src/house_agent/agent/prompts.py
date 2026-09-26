"""Prompt text for the search agent.

SYSTEM is identical on every call so it can be cached; everything run-specific goes in the
user message.
"""

from __future__ import annotations

from ..schemas import Criteria, LandPrefs
from .sources import SITE_NOTES, SITES, sites_for

SYSTEM = """\
You are a property-search assistant. You look through real-estate listing sites for one \
home buyer and report exactly what the pages show, through the submit tool you are given.

How to work:
- Use web_fetch to open search-result pages and individual listing pages. Use web_search \
to find a listing's page when you only have its address.
- Report only what you saw. Never guess a price, status or lot size; leave a field empty \
if the page didn't show it. If a page could not be loaded (blocked, rate-limited, error), \
say so in the notes instead of inventing results.
- Search pages often include "nearby" listings from other areas, and some are mis-geocoded. \
Check each listing's real city and state before including it.
- Listing sites (e.g. Redfin, Zillow, Realtor.com, Homes.com, LandWatch, Realtor.ca, Zolo, \
Point2 Homes) sometimes refuse \
automated access. If a site blocks you (403/429 error, CAPTCHA, "access denied", or a page \
with no listings where there should be some), don't retry or work around it; move on to the \
next site in the list and report the blocked site.
- The same house is often on several sites. Report it once, with whichever listing URL you \
used.
- When a page shows the listing's MLS number ("MLS# 60012345", "MLS® Number"), report it \
in mls_number; it identifies the same listing across sites.
- Never contact agents, submit forms, create accounts, or try to get past bot checks or \
CAPTCHAs.
- When you are done, call the submit tool once with all results. Don't write a prose \
summary instead of calling it.

Condition labels for homes:
- good: livable with no repair language.
- needs_updating: livable, but only needs cosmetic updating or "some TLC".
- reject: needs major repairs to be habitable (see the buyer's rules).
- unverified: you couldn't read the description.
Condition labels for vacant land (never use needs_updating for land):
- good: meets every must-have in the buyer's land preferences.
- unverified: the listing doesn't say whether a must-have is met (e.g. utilities not mentioned).
- reject: fails a must-have, or has something the buyer wants to avoid.
Condition notes: a short, factual line, e.g. "1940 farmhouse; new roof 2023; pole barn", \
"listing says needs some TLC", or for land "wooded, creek, power at road, perc test done, \
zoned AG". Mention price cuts you notice ("cut from $169,900 on 9/21").
"""


COUNTRY_NOTES = {
    "US": "Country: United States.",
    "CA": (
        "Country: Canada. Prices are in Canadian dollars. Use two-letter province codes "
        "(ON, BC, QC, ...) for the state field. Lot sizes are often listed in hectares "
        "(1 ha = 2.471 acres) or square feet (43,560 sq ft = 1 acre); always report acres. "
        '"Conditionally sold" / "sold conditional" means the same as contingent. Give '
        "drive_km (estimated driving distance in kilometres) along with drive_hours."
    ),
}


def criteria_block(c: Criteria) -> str:
    lines = [COUNTRY_NOTES[c.country], f"Property types: {', '.join(c.property_types) or 'any'}"]
    if c.min_price is not None or c.max_price is not None:
        lo = f"${c.min_price:,}" if c.min_price is not None else "any"
        hi = f"${c.max_price:,}" if c.max_price is not None else "any"
        lines.append(f"Price: {lo} to {hi}")
    if c.min_acres is not None or c.max_acres is not None:
        lines.append(
            f"Lot size: {c.min_acres if c.min_acres is not None else 0} acres"
            + (f" to {c.max_acres} acres" if c.max_acres is not None else " or more")
        )
    homes_only = " (homes only; doesn't apply to land)" if "land" in c.property_types else ""
    if c.min_beds and c.property_types != ["land"]:
        lines.append(f"Beds: at least {c.min_beds:g}{homes_only}")
    if c.min_baths and c.property_types != ["land"]:
        lines.append(f"Baths: at least {c.min_baths:g}{homes_only}")
    lines.append(
        "Status: active listings, and also pending / contingent / under-contract ones: report "
        "those with market_status pending or contingent (the app applies the buyer's choice "
        "about them). If the results page hides them, use its status filter to show them. "
        "Skip sold and off-market listings, auctions and short sales."
    )
    if c.anchors:
        lines.append("Anchors (estimate drive time to the nearest one; exclude beyond its limit):")
        for a in c.anchors:
            lines.append(f"  - {a.code}: {a.name}, max {a.max_drive_hours:g} hr drive")
    lines.append(
        "Nearby results from other areas: include them if within an anchor's drive limit."
        if c.include_nearby
        else "Only report listings located inside the area being searched."
    )
    homes = [t for t in c.property_types if t != "land"]
    if homes or not c.property_types:
        lines.append("Condition rules for homes:\n" + c.condition_rules.strip())
    if c.land is not None and ("land" in c.property_types or not c.property_types):
        lines.append(land_block(c.land))
    if c.extra_instructions.strip():
        lines.append("Other instructions:\n" + c.extra_instructions.strip())
    if c.feedback:
        lines.append(
            "The buyer's corrections to your earlier rejections (apply the same thinking to "
            "similar listings):\n" + "\n".join(f"  - {f}" for f in c.feedback)
        )
    return "\n".join(lines)


def land_block(land: LandPrefs) -> str:
    rows = [
        ("Intended use", land.uses),
        ("Must have (reject land without these)", land.must_have),
        ("Nice to have (mention in notes when present)", land.nice_to_have),
        ("Acceptable zoning", land.zoning or ["any"]),
        ("Avoid (reject)", land.avoid),
    ]
    body = "\n".join(f"  - {label}: {', '.join(vals)}" for label, vals in rows if vals)
    return "Vacant land preferences:\n" + body


def _money(price: float | None) -> str:
    return f"${price:,.0f}" if price is not None else "price unknown"


def _tracked_row(t: dict) -> str:
    mls = f" | MLS# {t['mls']}" if t.get("mls") else ""
    return (
        f"- ref {t['ref']}: {t['address']}, {t['city']}, {t['state']} | {_money(t['price'])}{mls}"
    )


def _item_rows(items: list[dict]) -> str:
    rows = []
    for i in items:
        urls = i.get("urls") or []
        where = " ; ".join(urls) if urls else "no URL on file"
        rows.append(f"{_tracked_row(i)} | URLs, best first: {where}")
    return "\n".join(rows)


def search_prompt(
    c: Criteria,
    region_label: str,
    region_anchor: str,
    plan: list[tuple[str, str | None]],
    tracked: list[dict],
    excluded: list[str],
    rejected: list[str] | None = None,
    fetch_budget: int | None = None,
    mode: str = "full",
) -> tuple[str, str]:
    """(shared, specific): the shared part is identical for every county searched in the same
    mode in a run (so it can be cached); the specific part is this county's."""
    if plan:
        lines = []
        for key, url in plan:
            name = SITES[key].name if key in SITES else key
            start = f" Start here: {url}" if url else ""
            lines.append(f"- {key} ({name}).{start}")
        notes = [SITE_NOTES[key] for key, _ in plan if key in SITE_NOTES]
        where = (
            "Listing sites to use for this county, in this order (the keys go in sites_used / "
            "sites_blocked):\n"
            + "\n".join(lines)
            + "\n"
            + "".join(n + "\n" for n in notes)
            + "Begin with the first site. If it blocks you, go to the next. If a starting URL "
            "doesn't show this county's listings, find the county's results page on that site "
            "with web_search. Check a second site too when the first shows only a few results, "
            "since each site misses some listings. web_search results (e.g. "
            f'"{region_label} land for sale" or "... homes for sale") can also lead you to '
            "listing pages on any of these sites. If you open Redfin's county results page, "
            "report its county ID (the number after /county/ in the URL)."
        )
    else:
        where = f"Find current listings in {region_label} with web_search."

    shared = ["Buyer's criteria:\n" + criteria_block(c)]
    if excluded:
        shared.append(
            "Ruled out by the buyer; never report these:\n" + "\n".join(f"- {e}" for e in excluded)
        )
    if mode == "sweep":
        shared.append(
            "This is a routine weekly sweep of a county searched before, working from results "
            "pages. Report every listing that passes the price, lot size, type and status "
            "filters and isn't tracked, ruled out, or previously rejected at the same or a "
            "higher price. Report them with condition unverified and condition_notes summing up "
            "what the results card shows; don't open listing pages to judge condition (another "
            "reviewer reads each new one). Open a listing page only when its card doesn't show "
            "price, lot size, type or location. Include days_on_market when shown. Don't report "
            "listings the results page already shows fail the filters. Then call "
            "submit_search_results."
        )
    else:
        shared.append(
            "For every listing that matches the price/lot/type filters and isn't tracked, ruled "
            "out or previously rejected at the same or a higher price, read its listing page's "
            "description (within the page budget) and label its condition. Report every "
            "candidate: the matches, and the ones you reject (condition reject, with a "
            "one-sentence reject_reason addressed to the buyer naming the rule it failed, e.g. "
            '"Listing says it needs a new roof and foundation work; you asked for cosmetic '
            'updates only."). The buyer reviews rejections, so be specific. Include '
            "days_on_market when shown. Don't report listings the results page already shows "
            "fail price, lot size or property type. Then call submit_search_results."
        )

    specific = [
        f"Search {region_label} for listings that match the buyer's criteria (above). "
        f"This area is searched for anchor {region_anchor}.",
        where,
    ]
    if fetch_budget:
        specific.append(
            f"Page budget: you can open about {fetch_budget} pages for this county, results "
            "pages included, so spend them where they matter. Read results pages first and "
            "judge listings from their cards (price, lot size, type, status, location). Open a "
            "listing's own page only for candidates that pass those filters, most promising "
            "first. If the budget runs out, still report the candidates you didn't open, with "
            'condition unverified and condition_notes "not opened yet", instead of dropping them.'
        )
    if tracked:
        specific.append(
            "Already tracked; don't open these or report them as new listings. When one of them "
            "appears on a results page you're reading, add it to seen_tracked with its ref and "
            "the price and status shown there (and its URL on that site and MLS number, if "
            "shown). Don't go looking for them; just note the ones you come across:\n"
            + "\n".join(_tracked_row(t) for t in tracked)
        )
    if rejected:
        specific.append(
            "Rejected before; skip these unless the price shown now is lower than listed here:\n"
            + "\n".join(f"- {r}" for r in rejected)
        )
    return "\n\n".join(shared), "\n\n".join(specific)


def status_prompt(c: Criteria, items: list[dict]) -> str:
    sites = ", ".join(SITES[k].name for k in sites_for(c))
    return (
        "Quick status check of listings the buyer tracks: for each one, find out whether it "
        "is still for sale and at what price. Don't judge its condition.\n\n"
        f"{_item_rows(items)}\n\n"
        f"{COUNTRY_NOTES[c.country]}\n\n"
        "How, cheapest first:\n"
        '1. web_search for its MLS number (e.g. "MLS# 60012345"), or without one its full '
        'address plus "for sale". Result snippets often show the price and status (for sale, '
        "pending, sold, off market) on several sites. If the snippets agree and look current, "
        "that's enough; don't open a page.\n"
        "2. Otherwise open its URLs in the order given. If a URL is gone or says the listing "
        "was removed, put it in dead_urls and try the next.\n"
        f"3. If none of that works, look for it on another site ({sites}).\n"
        "Status: active (for sale), pending, contingent (under contract / conditionally sold), "
        "sold, off_market (withdrawn, expired, cancelled), not_found (no trace of a current "
        "listing), unknown (couldn't tell, e.g. every page blocked).\n"
        "Report every ref exactly once, with the URL where you confirmed it and its MLS number "
        "if you saw one. Then call submit_status_results."
    )


def check_prompt(c: Criteria, items: list[dict]) -> str:
    sites = ", ".join(SITES[k].name for k in sites_for(c))
    return (
        "Re-read these tracked listings: their price or status changed, or their condition "
        "hasn't been read yet. For each one, open its listing page (try the URLs in the order "
        "given; if they fail, search for its MLS number or address) and report its current "
        "status and price. Read the description and label its condition. If you label one "
        "reject, give a one-sentence reject_reason addressed to the buyer.\n\n"
        f"{_item_rows(items)}\n\nBuyer's criteria:\n{criteria_block(c)}\n\n"
        "If a URL is gone or says the listing was removed, put it in dead_urls. If every page "
        f"is blocked or gone, find the listing on another site ({sites}).\n"
        "Report every ref exactly once, using status 'unknown' if you couldn't load it, with "
        "the URL you used and its MLS number if shown. Then call submit_check_results."
    )
