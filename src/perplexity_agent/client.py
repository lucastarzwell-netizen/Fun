"""Web-grounded answers via the Perplexity Agent API.

Wraps the official `perplexity` SDK's `client.responses.create(...)` call
(POST /v1/agent) so the rest of the project can ask a grounded question
without touching request/response shapes directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from perplexity import AuthenticationError, Perplexity, RateLimitError


class MissingAPIKeyError(RuntimeError):
    """Raised when PERPLEXITY_API_KEY is not set in the environment."""

    def __init__(self) -> None:
        super().__init__(
            "PERPLEXITY_API_KEY is not set. Create a key in the API Console "
            "(https://console.perplexity.ai) and export it in your own shell, "
            "e.g. `export PERPLEXITY_API_KEY=...` -- never paste the key into chat."
        )


class AgentAPIError(RuntimeError):
    """Base class for Perplexity Agent API errors raised by this module."""


class AgentAuthenticationError(AgentAPIError):
    """The API rejected the request with 401. The key is missing/invalid/expired."""

    def __init__(self) -> None:
        super().__init__(
            "Perplexity Agent API returned 401 Unauthorized. Verify PERPLEXITY_API_KEY is a "
            "current key from https://console.perplexity.ai. If this key was ever exposed "
            "(committed, logged, pasted somewhere public), rotate it there immediately."
        )


class AgentRateLimitError(AgentAPIError):
    """The API returned 429 (rate limited, or a model is temporarily overloaded)."""

    def __init__(self, retry_after: str | None) -> None:
        self.retry_after = retry_after
        suffix = f" Retry-After: {retry_after}s." if retry_after else " No Retry-After given."
        super().__init__(f"Perplexity Agent API returned 429 (rate limited).{suffix}")


@dataclass
class Citation:
    url: str
    title: str | None = None


@dataclass
class AgentAnswer:
    id: str
    text: str
    status: str
    citations: list[Citation] = field(default_factory=list)
    raw: Any = None


def _require_api_key() -> None:
    if not os.environ.get("PERPLEXITY_API_KEY"):
        raise MissingAPIKeyError()


def get_client() -> Perplexity:
    """Build a Perplexity SDK client, reading PERPLEXITY_API_KEY from the environment."""
    _require_api_key()
    return Perplexity()


def _extract_citations(response: Any) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[str] = set()

    def _add(url: str | None, title: str | None) -> None:
        if url and url not in seen:
            seen.add(url)
            citations.append(Citation(url=url, title=title))

    for item in getattr(response, "output", None) or []:
        item_type = getattr(item, "type", None)
        if item_type == "message":
            for content in getattr(item, "content", None) or []:
                for annotation in getattr(content, "annotations", None) or []:
                    _add(getattr(annotation, "url", None), getattr(annotation, "title", None))
        elif item_type == "search_results":
            for result in getattr(item, "results", None) or []:
                _add(getattr(result, "url", None), getattr(result, "title", None))

    return citations


def ask(
    query: str,
    *,
    preset: str | None = "low",
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    instructions: str | None = None,
    previous_response_id: str | None = None,
    response_format: dict[str, Any] | None = None,
    client: Perplexity | None = None,
) -> AgentAnswer:
    """Ask a web-grounded question via the Perplexity Agent API.

    Pass `model` to bypass presets and pick a specific frontier model; a
    web_search tool is added automatically in that case unless `tools` is
    given explicitly. Otherwise `preset` (default "low") selects a bundled
    model/tools/limits configuration that already includes web grounding.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    client = client or get_client()

    kwargs: dict[str, Any] = {"input": query}
    if model:
        kwargs["model"] = model
        kwargs["tools"] = tools if tools is not None else [{"type": "web_search"}]
    else:
        kwargs["preset"] = preset
        if tools is not None:
            kwargs["tools"] = tools
    if instructions:
        kwargs["instructions"] = instructions
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
    if response_format:
        kwargs["response_format"] = response_format

    try:
        response = client.responses.create(**kwargs)
    except RateLimitError as exc:
        retry_after = None
        resp = getattr(exc, "response", None)
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
        raise AgentRateLimitError(retry_after) from exc
    except AuthenticationError as exc:
        raise AgentAuthenticationError() from exc

    return AgentAnswer(
        id=response.id,
        text=response.output_text,
        status=getattr(response, "status", "completed"),
        citations=_extract_citations(response),
        raw=response,
    )
