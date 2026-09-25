"""Prompt text for the search agent.

SYSTEM is identical on every call so it can be cached; everything run-specific goes in the
user message.
"""

from __future__ import annotations

from ..schemas import Criteria, LandPrefs
from .sources import SITES, sites_for

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


def search_prompt(
    c: Criteria,
    region_label: str,
    region_anchor: str,
    plan: list[tuple[str, str | None]],
    known: list[str],
    excluded: list[str],
    rejected: list[str] | None = None,
) -> str:
    if plan:
        lines = []
        for key, url in plan:
            name = SITES[key].name if key in SITES else key
            start = f" Start here: {url}" if url else ""
            lines.append(f"- {key} ({name}).{start}")
        where = (
            "Listing sites to use for this county, in this order (the keys go in sites_used / "
            "sites_blocked):\n" + "\n".join(lines) + "\n"
            "Begin with the first site. If it blocks you, go to the next. If a starting URL "
            "doesn't show this county's listings, find the county's results page on that site "
            "with web_search. Check a second site too when the first shows only a few results, "
            "since each site misses some listings. web_search results (e.g. "
            f'"{region_label} land for sale" or "... homes for sale") can also lead you to '
            "listing pages on any of these sites. If you open Redfin's county results page, "
            "report its county ID (the number after /county/ in the URL)."
        )
    else:
        where = f"Find current listings in {region_label} with web_search."
    parts = [
        f"Search {region_label} for listings that match the buyer's criteria. "
        f"This area is searched for anchor {region_anchor}.",
        where,
        "Buyer's criteria:\n" + criteria_block(c),
    ]
    if known:
        parts.append(
            "Already tracked; skip these (don't open or report them):\n"
            + "\n".join(f"- {k}" for k in known)
        )
    if excluded:
        parts.append(
            "Ruled out by the buyer; never report these:\n" + "\n".join(f"- {e}" for e in excluded)
        )
    if rejected:
        parts.append(
            "You rejected these before; skip them unless the price shown now is lower than "
            "listed here:\n" + "\n".join(f"- {r}" for r in rejected)
        )
    parts.append(
        "For every other listing that matches the price/lot/type filters, open its listing "
        "page, read the description, and label its condition. Report every listing you "
        "opened: the matches, and the ones you reject (condition reject, with a one-sentence "
        'reject_reason addressed to the buyer naming the rule it failed, e.g. "Listing says '
        'it needs a new roof and foundation work; you asked for cosmetic updates only."). '
        "The buyer reviews rejections, so be specific. Don't report listings the results page "
        "already shows fail price, lot size or property type. Then call submit_search_results."
    )
    return "\n\n".join(parts)


def check_prompt(c: Criteria, items: list[dict]) -> str:
    sites = ", ".join(SITES[k].name for k in sites_for(c))
    rows = "\n".join(
        f"- ref {i['ref']}: {i['address']}, {i['city']}, {i['state']} | "
        f"price on file {i['price']} | {i['url'] or 'no URL on file'}"
        for i in items
    )
    return (
        "Re-check these tracked listings. For each one, open its listing page (search for it "
        "if there's no URL or the URL fails) and report its current status and price. Also "
        "re-read the description and label its condition. If you label one reject, give a "
        "one-sentence reject_reason addressed to the buyer.\n\n"
        f"{rows}\n\nBuyer's criteria:\n{criteria_block(c)}\n\n"
        "If a listing's page is blocked or gone, search for the address and check it on "
        f"another site ({sites}).\n"
        "Report every ref exactly once, using status 'unknown' if you couldn't load it. Then "
        "call submit_check_results."
    )
