"""Prompt text for the search agent.

SYSTEM is identical on every call so it can be cached; everything run-specific goes in the
user message.
"""

from __future__ import annotations

from ..schemas import Criteria

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
- Realtor.com blocks automated access; don't use it.
- Never contact agents, submit forms, create accounts, or try to get past bot checks or \
CAPTCHAs.
- When you are done, call the submit tool once with all results. Don't write a prose \
summary instead of calling it.

Condition labels:
- good: livable with no repair language.
- needs_updating: livable, but only needs cosmetic updating or "some TLC".
- reject: needs major repairs to be habitable (see the buyer's rules).
- unverified: you couldn't read the description.
Condition notes: a short, factual line, e.g. "1940 farmhouse; new roof 2023; pole barn" or \
"listing says needs some TLC". Mention price cuts you notice ("cut from $169,900 on 9/21").
"""


def criteria_block(c: Criteria) -> str:
    lines = [f"Property types: {', '.join(c.property_types) or 'any'}"]
    if c.min_price is not None or c.max_price is not None:
        lo = f"${c.min_price:,}" if c.min_price is not None else "any"
        hi = f"${c.max_price:,}" if c.max_price is not None else "any"
        lines.append(f"Price: {lo} to {hi}")
    if c.min_acres is not None or c.max_acres is not None:
        lines.append(
            f"Lot size: {c.min_acres if c.min_acres is not None else 0} acres"
            + (f" to {c.max_acres} acres" if c.max_acres is not None else " or more")
        )
    if c.min_beds:
        lines.append(f"Beds: at least {c.min_beds:g}")
    if c.min_baths:
        lines.append(f"Baths: at least {c.min_baths:g}")
    lines.append(
        "Status: active listings only (exclude pending, contingent, under contract, sold, "
        "off-market, auctions, short sales)."
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
    lines.append("Condition rules:\n" + c.condition_rules.strip())
    if c.extra_instructions.strip():
        lines.append("Other instructions:\n" + c.extra_instructions.strip())
    return "\n".join(lines)


def search_prompt(
    c: Criteria,
    region_label: str,
    region_anchor: str,
    url: str | None,
    known: list[str],
    excluded: list[str],
) -> str:
    where = (
        f"Start from this search page: {url}\nCheck that the page title names the right area."
        if url
        else f"Find the Redfin search-results page for {region_label} with web_search (its URL "
        "looks like https://www.redfin.com/county/<ID>/<ST>/<Name>-County), open it with "
        "web_fetch, and report the county ID. If Redfin isn't reachable, use another listing "
        "site that allows automated access."
    )
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
    parts.append(
        "For every other listing that matches the price/lot/type filters, open its listing "
        "page, read the description, and label its condition. Report matches (including "
        "needs_updating ones; you may leave out rejects). Then call submit_search_results."
    )
    return "\n\n".join(parts)


def check_prompt(c: Criteria, items: list[dict]) -> str:
    rows = "\n".join(
        f"- ref {i['ref']}: {i['address']}, {i['city']}, {i['state']} | "
        f"price on file {i['price']} | {i['url'] or 'no URL on file'}"
        for i in items
    )
    return (
        "Re-check these tracked listings. For each one, open its listing page (search for it "
        "if there's no URL or the URL fails) and report its current status and price. Also "
        "re-read the description and label its condition.\n\n"
        f"{rows}\n\nBuyer's criteria:\n{criteria_block(c)}\n\n"
        "Report every ref exactly once, using status 'unknown' if you couldn't load it. Then "
        "call submit_check_results."
    )
