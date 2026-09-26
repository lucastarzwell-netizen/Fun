from house_agent.agent.claude_agent import AgentError, Usage
from house_agent.agent.types import CheckResult, SearchResult, StatusCheck, StatusCheckResult

_STATUS_FIELDS = set(StatusCheck.model_fields)


class FakeAgent:
    """Scripted agent.

    `checks` maps address -> check kwargs, used for quick status checks (status/price/url
    fields only) and condition re-reads (everything). `regions` maps region label ->
    SearchResult dict (or an exception); a region's "seen" list names tracked listings by
    address that the search saw on a results page, e.g. {"address": ..., "price": ...}.
    """

    def __init__(self, checks=None, regions=None):
        self.checks = checks or {}
        self.regions = regions or {}
        self.usage = Usage()
        self.search_calls = []
        self.status_calls = []
        self.reread_calls = []

    def status_check(self, criteria, items):
        self.status_calls.append([i["address"] for i in items])
        out = []
        for item in items:
            spec = self.checks.get(item["address"], {"status": "active"})
            if isinstance(spec, Exception):
                raise spec
            out.append(
                {"ref": item["ref"], **{k: v for k, v in spec.items() if k in _STATUS_FIELDS}}
            )
        return StatusCheckResult.model_validate({"checks": out})

    def check_listings(self, criteria, items):
        self.reread_calls.append([i["address"] for i in items])
        out = []
        for item in items:
            spec = self.checks.get(item["address"], {"status": "active"})
            out.append({"ref": item["ref"], **spec})
        return CheckResult.model_validate({"checks": out})

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
    ):
        self.search_calls.append(
            {
                "label": region_label,
                "plan": plan,
                "tracked": tracked,
                "excluded": excluded,
                "rejected": rejected,
                "fetch_budget": fetch_budget,
            }
        )
        result = self.regions.get(region_label, {"listings": [], "region_checked": True})
        if isinstance(result, Exception):
            raise result
        result = dict(result)
        refs = {t["address"]: t["ref"] for t in tracked}
        seen = result.pop("seen", [])
        result["seen_tracked"] = [
            {"ref": refs[s["address"]], **{k: v for k, v in s.items() if k != "address"}}
            for s in seen
            if s["address"] in refs
        ]
        return SearchResult.model_validate(result)


__all__ = ["FakeAgent", "AgentError"]
