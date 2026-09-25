"""Setup-wizard helper: turn "places I want to be near" into counties to search.

One structured-output call, no tools, so the wizard gets an answer in seconds. Redfin
county IDs are left for the first search run to discover (see runner.py).
"""

from __future__ import annotations

import anthropic
from pydantic import BaseModel, Field

from ..config import settings
from .claude_agent import AgentError


class AnchorInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    max_drive_hours: float = Field(gt=0, le=8)


class SuggestIn(BaseModel):
    anchors: list[AnchorInput] = Field(min_length=1, max_length=6)
    property_types: list[str] = ["house"]
    min_acres: float | None = None
    max_price: int | None = None


class ResolvedAnchor(BaseModel):
    input: str = Field(description="The location exactly as the user typed it")
    name: str = Field(
        description="Unambiguous description, e.g. 'Detroit Metropolitan Airport, Romulus, MI', "
        "'ZIP 48823 (East Lansing, MI)' or '123 Main St, Ann Arbor, MI'"
    )
    code: str = Field(
        description="2-5 letter label: an airport code (DTW), a ZIP code, or short initials"
    )
    state: str = Field(description="Two-letter US state code")


class SuggestedRegion(BaseModel):
    name: str = Field(description="County name including the word County, e.g. 'Lenawee County'")
    state: str = Field(description="Two-letter state code")
    anchor: str = Field(description="Code of the anchor this county is near")
    est_drive_hours: float = Field(description="Typical drive from the anchor to the county center")
    note: str = Field(description="One short phrase on why it fits, e.g. 'rural, lots of acreage'")


class SuggestOut(BaseModel):
    anchors: list[ResolvedAnchor]
    regions: list[SuggestedRegion]


PROMPT = """\
A home buyer is setting up a property search centered on the location(s) below. Each one \
is a street address, ZIP code, city, or landmark, with the longest drive they'd accept from \
it. For each location, identify it precisely and give it a short code (the airport code for \
airports, the ZIP for a ZIP code). Then list the US counties where most of the county is \
within that maximum drive time, nearest first.

If a location is ambiguous (e.g. "Springfield"), pick the most likely one and name it \
clearly so the buyer can spot a wrong guess.

Locations:
{places}

What they're looking for: {what}.

Guidance:
- Include counties that are realistic for this budget and lot size (e.g. rural and exurban \
counties when they want acreage on a modest budget) and skip dense urban-core counties where \
nothing would match.
- Up to 15 counties per location. Cross state lines when that's closer.
- Drive times are typical, non-rush-hour estimates.
"""


def suggest_regions(body: SuggestIn, client: anthropic.Anthropic | None = None) -> SuggestOut:
    places = "\n".join(f"- {a.name} (max {a.max_drive_hours:g} hr drive)" for a in body.anchors)
    what = ", ".join(body.property_types) or "any home"
    if body.max_price:
        what += f", up to ${body.max_price:,}"
    if body.min_acres:
        what += f", at least {body.min_acres:g} acres"
    try:
        client = client or anthropic.Anthropic()
        response = client.messages.parse(
            model=settings.model,
            max_tokens=16000,
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": PROMPT.format(places=places, what=what)}],
            output_format=SuggestOut,
        )
    except anthropic.AuthenticationError as e:
        raise AgentError("the Claude API key is invalid") from e
    except anthropic.APIStatusError as e:
        raise AgentError(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AgentError("couldn't reach the Claude API") from e
    except TypeError as e:  # the SDK found no credentials at all
        raise AgentError("no Claude API key is set up on the server") from e
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise AgentError("Couldn't get county suggestions; add counties by hand instead.")
    out = response.parsed_output
    seen: set[str] = set()
    for anchor in out.anchors:  # codes group counties in the UI, so they must be unique
        anchor.code = anchor.code.strip().upper()[:8] or "HOME"
        base, n = anchor.code, 2
        while anchor.code in seen:
            anchor.code, n = f"{base}{n}", n + 1
        seen.add(anchor.code)
    known = {a.code for a in out.anchors}
    out.regions = [r for r in out.regions if r.anchor in known]
    return out
