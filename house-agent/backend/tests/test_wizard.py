from types import SimpleNamespace

from fastapi.testclient import TestClient

from house_agent.agent.claude_agent import AgentError
from house_agent.agent.suggest import SuggestIn, SuggestOut, suggest_regions
from house_agent.main import app

OUT = SuggestOut.model_validate(
    {
        "anchors": [
            {
                "input": "detroit airport",
                "name": "Detroit Metropolitan Airport",
                "code": "DTW",
                "state": "MI",
            }
        ],
        "regions": [
            {
                "name": "Monroe County",
                "state": "MI",
                "anchor": "DTW",
                "est_drive_hours": 0.6,
                "note": "rural south",
            },
            {
                "name": "Nowhere County",
                "state": "ZZ",
                "anchor": "XXX",
                "est_drive_hours": 1,
                "note": "bad anchor",
            },
        ],
    }
)


class FakeClient:
    def __init__(self, out, stop_reason="end_turn"):
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)
        self.out, self.stop_reason = out, stop_reason

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.out, stop_reason=self.stop_reason)


BODY = SuggestIn(
    anchors=[{"name": "detroit airport", "max_drive_hours": 2}], max_price=175000, min_acres=1
)


def test_suggest_builds_prompt_and_drops_unknown_anchors():
    client = FakeClient(OUT.model_copy(deep=True))
    out = suggest_regions(BODY, client=client)
    assert [r.name for r in out.regions] == ["Monroe County"]
    prompt = client.calls[0]["messages"][0]["content"]
    assert "detroit airport (max 2 hr drive)" in prompt
    assert "up to $175,000, at least 1 acres" in prompt
    assert client.calls[0]["output_format"] is SuggestOut


def test_suggest_refusal_raises():
    try:
        suggest_regions(BODY, client=FakeClient(None, "refusal"))
    except AgentError:
        return
    raise AssertionError("expected AgentError")


def test_wizard_endpoint(monkeypatch):
    monkeypatch.setattr("house_agent.api.wizard.suggest_regions", lambda body: OUT)
    with TestClient(app) as client:
        r = client.post("/api/wizard/regions", json=BODY.model_dump())
        assert r.status_code == 200
        assert r.json()["anchors"][0]["code"] == "DTW"


def test_wizard_endpoint_reports_agent_errors(monkeypatch):
    def boom(body):
        raise AgentError("The Claude API key is missing or invalid.")

    monkeypatch.setattr("house_agent.api.wizard.suggest_regions", boom)
    with TestClient(app) as client:
        r = client.post("/api/wizard/regions", json=BODY.model_dump())
        assert r.status_code == 503 and "API key" in r.json()["detail"]


def test_wizard_rejects_empty_anchors():
    with TestClient(app) as client:
        assert client.post("/api/wizard/regions", json={"anchors": []}).status_code == 422
