"""Unit tests for perplexity_agent.client. No network calls -- the SDK client is mocked."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from perplexity_agent import client as client_module
from perplexity_agent.client import (
    AgentAuthenticationError,
    AgentRateLimitError,
    MissingAPIKeyError,
    ask,
)


class _FakeRateLimitError(Exception):
    def __init__(self, retry_after: str | None) -> None:
        super().__init__("rate limited")
        self.response = SimpleNamespace(headers={"Retry-After": retry_after} if retry_after else {})


class _FakeAuthenticationError(Exception):
    pass


def _fake_response(text: str = "Paris is the capital of France.") -> SimpleNamespace:
    annotation = SimpleNamespace(url="https://example.com/a", title="Example A")
    content = SimpleNamespace(annotations=[annotation])
    message_item = SimpleNamespace(type="message", content=[content])
    search_result = SimpleNamespace(url="https://example.com/b", title="Example B")
    search_results_item = SimpleNamespace(type="search_results", results=[search_result])
    return SimpleNamespace(
        id="resp_123",
        status="completed",
        output_text=text,
        output=[message_item, search_results_item],
    )


def test_ask_requires_non_empty_query() -> None:
    with pytest.raises(ValueError):
        ask("   ")


def test_ask_raises_missing_api_key_without_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError):
        ask("What is the capital of France?")


def test_ask_uses_preset_by_default() -> None:
    fake_client = mock.Mock()
    fake_client.responses.create.return_value = _fake_response()

    answer = ask("What is the capital of France?", client=fake_client)

    fake_client.responses.create.assert_called_once_with(
        input="What is the capital of France?", preset="low"
    )
    assert answer.id == "resp_123"
    assert answer.text == "Paris is the capital of France."
    assert answer.status == "completed"


def test_ask_with_model_defaults_to_web_search_tool() -> None:
    fake_client = mock.Mock()
    fake_client.responses.create.return_value = _fake_response()

    ask("Latest AI news?", model="openai/gpt-5.6-sol", client=fake_client)

    fake_client.responses.create.assert_called_once_with(
        input="Latest AI news?",
        model="openai/gpt-5.6-sol",
        tools=[{"type": "web_search"}],
    )


def test_ask_respects_explicit_tools_override() -> None:
    fake_client = mock.Mock()
    fake_client.responses.create.return_value = _fake_response()

    ask("Question", model="openai/gpt-5.6-sol", tools=[{"type": "fetch_url"}], client=fake_client)

    _, kwargs = fake_client.responses.create.call_args
    assert kwargs["tools"] == [{"type": "fetch_url"}]


def test_ask_extracts_citations_from_annotations_and_search_results() -> None:
    fake_client = mock.Mock()
    fake_client.responses.create.return_value = _fake_response()

    answer = ask("Question", client=fake_client)

    urls = {c.url for c in answer.citations}
    assert urls == {"https://example.com/a", "https://example.com/b"}


def test_ask_passes_through_previous_response_id_and_response_format() -> None:
    fake_client = mock.Mock()
    fake_client.responses.create.return_value = _fake_response()

    ask(
        "Follow-up question",
        previous_response_id="resp_abc",
        response_format={"type": "json_schema", "json_schema": {"name": "answer", "schema": {}}},
        client=fake_client,
    )

    _, kwargs = fake_client.responses.create.call_args
    assert kwargs["previous_response_id"] == "resp_abc"
    assert kwargs["response_format"]["type"] == "json_schema"


def test_ask_translates_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "RateLimitError", _FakeRateLimitError)
    fake_client = mock.Mock()
    fake_client.responses.create.side_effect = _FakeRateLimitError("12")

    with pytest.raises(AgentRateLimitError) as exc_info:
        ask("Question", client=fake_client)
    assert exc_info.value.retry_after == "12"


def test_ask_translates_authentication_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "AuthenticationError", _FakeAuthenticationError)
    fake_client = mock.Mock()
    fake_client.responses.create.side_effect = _FakeAuthenticationError("unauthorized")

    with pytest.raises(AgentAuthenticationError):
        ask("Question", client=fake_client)
