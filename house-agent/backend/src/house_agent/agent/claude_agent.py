"""Claude-backed implementation of the search agent.

Each task is one conversation: Claude browses with the server-side web_search / web_fetch
tools, then reports through a custom `submit_*` tool whose input we validate with Pydantic.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from ..config import settings
from ..schemas import Criteria
from . import prompts
from .sources import site_for_url
from .types import CheckResult, SearchResult, StatusCheckResult

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_TURNS = 10


class SearchAgent(Protocol):
    """What the runner needs from an agent; tests use a fake."""

    usage: Usage

    def search_region(
        self,
        criteria: Criteria,
        region_label: str,
        region_anchor: str,
        plan: list[tuple[str, str | None]],
        tracked: list[dict],
        excluded: list[str],
        rejected: list[str] | None = None,
        fetch_budget: int | None = None,
    ) -> SearchResult: ...

    def status_check(self, criteria: Criteria, items: list[dict]) -> StatusCheckResult: ...

    def check_listings(self, criteria: Criteria, items: list[dict]) -> CheckResult: ...


# $ per million tokens (input, output). Cache reads bill at 0.1x input, cache writes 1.25x.
# Estimates for the Runs page only; server-tool fees (web search/fetch) are not included.
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

_COUNTERS = (
    "calls",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "web_searches",
    "web_fetches",
)


def estimate_cost(model: str, counts: dict[str, int]) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    per_in, per_out = price[0] / 1e6, price[1] / 1e6
    return (
        counts.get("input_tokens", 0) * per_in
        + counts.get("output_tokens", 0) * per_out
        + counts.get("cache_read_tokens", 0) * per_in * 0.1
        + counts.get("cache_write_tokens", 0) * per_in * 1.25
    )


@dataclass
class Usage:
    """Token and tool counts, per model (the check model and the search model differ)."""

    by_model: dict[str, dict[str, int]] = field(default_factory=dict)
    # Per listing site: pages opened, characters of page text returned, failed fetches.
    by_site: dict[str, dict[str, int]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def add_fetch(self, site: str, chars: int, failed: bool) -> None:
        c = self.by_site.setdefault(site, {"pages": 0, "chars": 0, "errors": 0})
        c["pages"] += 1
        c["chars"] += chars
        c["errors"] += int(failed)

    def add(self, usage: Any, model: str = "unknown") -> None:
        c = self.by_model.setdefault(model, dict.fromkeys(_COUNTERS, 0))
        c["calls"] += 1
        c["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
        c["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
        c["cache_read_tokens"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        c["cache_write_tokens"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        stu = getattr(usage, "server_tool_use", None)
        if stu is not None:
            c["web_searches"] += getattr(stu, "web_search_requests", 0) or 0
            c["web_fetches"] += getattr(stu, "web_fetch_requests", 0) or 0

    def total(self, key: str) -> int:
        return sum(c.get(key, 0) for c in self.by_model.values())

    def snapshot(self) -> dict[str, dict]:
        return {
            "models": {m: dict(c) for m, c in self.by_model.items()},
            "sites": {k: dict(c) for k, c in self.by_site.items()},
        }

    def since(self, snapshot: dict[str, dict]) -> dict[str, Any]:
        """Counts added after `snapshot`, in the same shape as as_dict()."""
        diff = Usage()
        for model, c in self.by_model.items():
            before = snapshot["models"].get(model, {})
            diff.by_model[model] = {k: c.get(k, 0) - before.get(k, 0) for k in _COUNTERS}
        diff.by_model = {m: c for m, c in diff.by_model.items() if c["calls"]}
        for site, c in self.by_site.items():
            before = snapshot["sites"].get(site, {})
            d = {k: c[k] - before.get(k, 0) for k in c}
            if d["pages"]:
                diff.by_site[site] = d
        return diff.as_dict()

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {k: self.total(k) for k in _COUNTERS}
        costs = {m: estimate_cost(m, c) for m, c in self.by_model.items()}
        out["by_model"] = {
            m: {**c, "est_cost_usd": None if costs[m] is None else round(costs[m], 4)}
            for m, c in self.by_model.items()
        }
        known = [v for v in costs.values() if v is not None]
        out["est_cost_usd"] = round(sum(known), 4) if known else None
        out["by_site"] = {k: dict(c) for k, c in sorted(self.by_site.items())}
        return out


class AgentError(RuntimeError):
    pass


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic emits $defs/$ref; inline them so the tool schema is self-contained."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "title")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def submit_tool(name: str, description: str, model: type[BaseModel]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": _inline_refs(model.model_json_schema()),
    }


SEARCH_TOOL = submit_tool(
    "submit_search_results",
    "Submit the matching listings found in this area. Call once, when finished.",
    SearchResult,
)
CHECK_TOOL = submit_tool(
    "submit_check_results",
    "Submit the re-check results for every ref. Call once, when finished.",
    CheckResult,
)
STATUS_TOOL = submit_tool(
    "submit_status_results",
    "Submit the status of every ref. Call once, when finished.",
    StatusCheckResult,
)


def _record_fetches(usage: Usage, content: list) -> None:
    """Count each page the agent opened, by site: how much text came back, or that it failed.
    Page text is what the model reads, so this shows which sites are expensive to search."""
    urls = {
        b.id: (b.input or {}).get("url", "")
        for b in content
        if getattr(b, "type", "") == "server_tool_use" and getattr(b, "name", "") == "web_fetch"
    }
    for block in content:
        if getattr(block, "type", "") != "web_fetch_tool_result":
            continue
        result = block.content
        if getattr(result, "type", "") == "web_fetch_result":
            source = getattr(getattr(result, "content", None), "source", None)
            data = getattr(source, "data", "")
            usage.add_fetch(
                site_for_url(result.url), len(data) if isinstance(data, str) else 0, False
            )
        else:
            usage.add_fetch(site_for_url(urls.get(block.tool_use_id, "")), 0, True)


def _supports_fallbacks(model: str) -> bool:
    """Server-side refusal fallbacks ("default" routing) are for the Opus 5 / Fable 5 tiers."""
    return model.startswith(("claude-opus-5", "claude-fable-5"))


class ClaudeSearchAgent:
    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        check_model: str | None = None,
        sweep_model: str | None = None,
    ):
        self.client = client or anthropic.Anthropic()
        self.model = model or settings.model
        self.check_model = check_model or settings.check_model
        self.sweep_model = sweep_model or settings.sweep_model
        self.usage = Usage()

    # -- public API --------------------------------------------------------------------

    def search_region(
        self,
        criteria,
        region_label,
        region_anchor,
        plan,
        tracked,
        excluded,
        rejected=None,
        fetch_budget=None,
        mode="full",
    ):
        """mode "full": judge every candidate (main model). "sweep": a routine pass with the
        cheaper sweep model that reports new candidates unverified for the main model to read."""
        budget = fetch_budget or settings.search_fetches
        prompt = prompts.search_prompt(
            criteria, region_label, region_anchor, plan, tracked, excluded, rejected, budget, mode
        )
        sweep = mode == "sweep"
        return self._run(
            prompt,
            SEARCH_TOOL,
            SearchResult,
            model=self.sweep_model if sweep else self.model,
            effort=settings.sweep_effort if sweep else settings.effort,
            fetch_budget=budget,
            search_budget=settings.search_web_searches,
        )

    def status_check(self, criteria, items):
        prompt = prompts.status_prompt(criteria, items)
        return self._run(
            prompt,
            STATUS_TOOL,
            StatusCheckResult,
            model=self.check_model,
            effort=settings.check_effort,
            fetch_budget=len(items) + 2,
            search_budget=len(items) * 2 + 2,
        )

    def check_listings(self, criteria, items):
        prompt = prompts.check_prompt(criteria, items)
        return self._run(
            prompt,
            CHECK_TOOL,
            CheckResult,
            model=self.model,
            effort=settings.effort,
            fetch_budget=len(items) * 2 + 2,
            search_budget=len(items) + 2,
        )

    # -- loop --------------------------------------------------------------------------

    def _tools(
        self, submit: dict[str, Any], fetch_budget: int, search_budget: int
    ) -> list[dict[str, Any]]:
        return [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": search_budget},
            {
                "type": "web_fetch_20260209",
                "name": "web_fetch",
                "max_uses": fetch_budget,
                "max_content_tokens": settings.page_tokens,
            },
            submit,
        ]

    def _run(
        self,
        prompt: str | tuple[str, str],
        submit: dict[str, Any],
        result_type: type[T],
        *,
        model: str,
        effort: str,
        fetch_budget: int,
        search_budget: int,
    ) -> T:
        if isinstance(prompt, tuple):
            # (shared, specific): the shared part is the same for every county in a run, so
            # cache it; later counties pay a tenth for it.
            shared, specific = prompt
            content: Any = [
                {"type": "text", "text": shared, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": specific},
            ]
        else:
            content = prompt
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        tools = self._tools(submit, fetch_budget, search_budget)
        extra: dict[str, Any] = {}
        if _supports_fallbacks(model):
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        nudged = False

        for _ in range(MAX_TURNS):
            try:
                with self.client.beta.messages.stream(
                    model=model,
                    max_tokens=64000,
                    system=[
                        {
                            "type": "text",
                            "text": prompts.SYSTEM,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    # Also cache the conversation so far: resuming after pause_turn resends
                    # every page already read.
                    cache_control={"type": "ephemeral"},
                    thinking={"type": "adaptive"},
                    output_config={"effort": effort},
                    tools=tools,
                    messages=messages,
                    **extra,
                ) as stream:
                    response = stream.get_final_message()
            except anthropic.APIStatusError as e:
                raise AgentError(f"Claude API error {e.status_code}: {e.message}") from e
            except anthropic.APIConnectionError as e:
                raise AgentError(f"Could not reach the Claude API: {e}") from e

            # Bill to the model that actually answered (a refusal fallback can switch it).
            _record_fetches(self.usage, response.content)
            served = getattr(response, "model", None)
            self.usage.add(response.usage, served if isinstance(served, str) else model)
            if response.stop_reason == "refusal":
                raise AgentError("The model declined this request.")

            submitted = next(
                (b for b in response.content if b.type == "tool_use" and b.name == submit["name"]),
                None,
            )
            if submitted is not None:
                try:
                    return result_type.model_validate(submitted.input)
                except ValidationError as e:
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": submitted.id,
                                    "is_error": True,
                                    "content": f"Invalid input, fix and resubmit: {e}",
                                }
                            ],
                        }
                    )
                    continue

            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue  # server-side tool loop hit its limit; resend to resume
            if response.stop_reason == "max_tokens":
                raise AgentError("Response hit max_tokens before submitting results.")
            if nudged:
                break
            nudged = True
            messages.append(
                {"role": "user", "content": f"Call {submit['name']} now with your results."}
            )

        raise AgentError(f"Agent finished without calling {submit['name']}.")
