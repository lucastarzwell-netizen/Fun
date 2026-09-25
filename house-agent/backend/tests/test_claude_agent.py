"""The agent loop against a fake Anthropic client (no network)."""

from types import SimpleNamespace

import pytest

from house_agent.agent.claude_agent import SEARCH_TOOL, AgentError, ClaudeSearchAgent
from house_agent.schemas import Criteria


def _resp(stop_reason, content):
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=0,
        server_tool_use=SimpleNamespace(web_search_requests=1, web_fetch_requests=2),
    )
    return SimpleNamespace(stop_reason=stop_reason, content=content, usage=usage)


def _tool_use(input_, id_="tu_1"):
    return SimpleNamespace(type="tool_use", name="submit_search_results", id=id_, input=input_)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        response = self.responses.pop(0)

        class _Ctx:
            def __enter__(self_inner):
                return SimpleNamespace(get_final_message=lambda: response)

            def __exit__(self_inner, *a):
                return False

        return _Ctx()


GOOD = {
    "region_checked": True,
    "listings": [{"address": "1 Farm Rd", "city": "Adrian", "state": "MI", "condition": "good"}],
}


def _search(agent):
    return agent.search_region(
        Criteria(), "Lenawee County, MI", "DTW", [("redfin", "https://x")], [], []
    )


def test_submit_tool_schema_is_self_contained():
    assert "$defs" not in str(SEARCH_TOOL["input_schema"])
    assert "$ref" not in str(SEARCH_TOOL["input_schema"])


def test_pause_turn_then_submit():
    client = FakeClient(
        [
            _resp("pause_turn", [SimpleNamespace(type="text", text="searching")]),
            _resp("tool_use", [_tool_use(GOOD)]),
        ]
    )
    agent = ClaudeSearchAgent(client=client, model="claude-opus-5")
    result = _search(agent)
    assert result.listings[0].address == "1 Farm Rd"
    assert agent.usage.calls == 2 and agent.usage.web_fetches == 4
    # The resumed request carries the paused assistant turn and no extra user message.
    assert client.requests[1]["messages"][-1]["role"] == "assistant"
    tools = {t["name"] for t in client.requests[0]["tools"]}
    assert tools == {"web_search", "web_fetch", "submit_search_results"}


def test_invalid_submission_is_sent_back_as_error():
    client = FakeClient(
        [
            _resp("tool_use", [_tool_use({"listings": "oops"})]),
            _resp("tool_use", [_tool_use(GOOD, "tu_2")]),
        ]
    )
    result = _search(ClaudeSearchAgent(client=client, model="claude-opus-5"))
    assert result.region_checked
    err = client.requests[1]["messages"][-1]["content"][0]
    assert err["is_error"] and err["tool_use_id"] == "tu_1"


def test_nudges_once_then_fails():
    text = [SimpleNamespace(type="text", text="done")]
    client = FakeClient([_resp("end_turn", text), _resp("end_turn", text)])
    with pytest.raises(AgentError):
        _search(ClaudeSearchAgent(client=client, model="claude-opus-5"))
    assert "submit_search_results" in client.requests[1]["messages"][-1]["content"]


def test_refusal_raises():
    client = FakeClient([_resp("refusal", [])])
    with pytest.raises(AgentError):
        _search(ClaudeSearchAgent(client=client, model="claude-opus-5"))
