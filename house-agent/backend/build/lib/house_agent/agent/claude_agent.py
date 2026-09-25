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
from .types import CheckResult, SearchResult

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
        url: str | None,
        known: list[str],
        excluded: list[str],
    ) -> SearchResult: ...

    def check_listings(self, criteria: Criteria, items: list[dict]) -> CheckResult: ...


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    web_searches: int = 0
    web_fetches: int = 0
    calls: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def add(self, usage: Any) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        stu = getattr(usage, "server_tool_use", None)
        if stu is not None:
            self.web_searches += getattr(stu, "web_search_requests", 0) or 0
            self.web_fetches += getattr(stu, "web_fetch_requests", 0) or 0

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "web_searches": self.web_searches,
            "web_fetches": self.web_fetches,
        }


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


class ClaudeSearchAgent:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str | None = None):
        self.client = client or anthropic.Anthropic()
        self.model = model or settings.model
        self.usage = Usage()

    # -- public API --------------------------------------------------------------------

    def search_region(self, criteria, region_label, region_anchor, url, known, excluded):
        prompt = prompts.search_prompt(criteria, region_label, region_anchor, url, known, excluded)
        return self._run(prompt, SEARCH_TOOL, SearchResult, fetch_budget=30)

    def check_listings(self, criteria, items):
        prompt = prompts.check_prompt(criteria, items)
        return self._run(prompt, CHECK_TOOL, CheckResult, fetch_budget=len(items) * 3 + 4)

    # -- loop --------------------------------------------------------------------------

    def _tools(self, submit: dict[str, Any], fetch_budget: int) -> list[dict[str, Any]]:
        return [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": 10},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": fetch_budget},
            submit,
        ]

    def _run(
        self, prompt: str, submit: dict[str, Any], result_type: type[T], fetch_budget: int
    ) -> T:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        tools = self._tools(submit, fetch_budget)
        nudged = False

        for _ in range(MAX_TURNS):
            try:
                with self.client.beta.messages.stream(
                    model=self.model,
                    max_tokens=64000,
                    system=[
                        {
                            "type": "text",
                            "text": prompts.SYSTEM,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    thinking={"type": "adaptive"},
                    output_config={"effort": settings.effort},
                    tools=tools,
                    messages=messages,
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                ) as stream:
                    response = stream.get_final_message()
            except anthropic.APIStatusError as e:
                raise AgentError(f"Claude API error {e.status_code}: {e.message}") from e
            except anthropic.APIConnectionError as e:
                raise AgentError(f"Could not reach the Claude API: {e}") from e

            self.usage.add(response.usage)

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
