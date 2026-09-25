"""Address normalization so the same house matches across sources and runs.

"17902 State Route 2, Wauseon, OH" and "17902 State Rte 2, Wauseon, OH" must produce
the same key, otherwise a re-listed or re-formatted house shows up as new.
"""

from __future__ import annotations

import re

_SUFFIXES = {
    "avenue": "ave",
    "av": "ave",
    "boulevard": "blvd",
    "circle": "cir",
    "court": "ct",
    "drive": "dr",
    "highway": "hwy",
    "lane": "ln",
    "parkway": "pkwy",
    "place": "pl",
    "road": "rd",
    "route": "rte",
    "rt": "rte",
    "street": "st",
    "terrace": "ter",
    "trail": "trl",
    "way": "way",
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "northeast": "ne",
    "northwest": "nw",
    "southeast": "se",
    "southwest": "sw",
    "county": "co",
    "apartment": "unit",
    "apt": "unit",
    "suite": "unit",
    "ste": "unit",
}


def _norm(text: str) -> str:
    text = text.lower().replace("#", " unit ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    words = [_SUFFIXES.get(w, w) for w in text.split()]
    return " ".join(words)


def address_key(address: str, city: str, state: str) -> str:
    return f"{_norm(address)}|{_norm(city)}|{state.strip().lower()}"
