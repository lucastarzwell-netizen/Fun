from house_agent.agent.claude_agent import AgentError, Usage
from house_agent.agent.types import CheckResult, SearchResult


class FakeAgent:
    """Scripted agent: `checks` maps address -> ListingCheck kwargs; `regions` maps
    region label -> SearchResult (or an exception)."""

    def __init__(self, checks=None, regions=None):
        self.checks = checks or {}
        self.regions = regions or {}
        self.usage = Usage()
        self.search_calls = []

    def check_listings(self, criteria, items):
        out = []
        for item in items:
            spec = self.checks.get(item["address"], {"status": "active"})
            out.append({"ref": item["ref"], **spec})
        return CheckResult.model_validate({"checks": out})

    def search_region(
        self, criteria, region_label, region_anchor, url, known, excluded, rejected=None
    ):
        self.search_calls.append((region_label, url, known, excluded, rejected))
        result = self.regions.get(region_label, {"listings": [], "region_checked": True})
        if isinstance(result, Exception):
            raise result
        return SearchResult.model_validate(result)


__all__ = ["FakeAgent", "AgentError"]
