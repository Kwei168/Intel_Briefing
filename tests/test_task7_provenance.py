"""
Task 7 - Provenance / Logging / CI contract tests.

Verifies:
1. Report-level provenance distinguishes precomputed / reused / agnes / gemini / rss_fallback
2. Item-level _provider / _model / _cached / _failure_reason fields
3. Structured logging contains safe fields only, no secrets
4. CI workflow has required env vars, secrets via ${{ secrets.* }}

No real network, no real keys.
"""
import logging
from pathlib import Path
import pytest
from unittest.mock import MagicMock

from src.utils.llm_provider import LLMResult, LLMCache, cache_key, AgnesBudget


def _empty_intel():
    return {key: [] for key in (
        "tech_trends", "capital_flow", "product_gems", "community",
        "research", "social", "insights",
    )}


# ---------------------------------------------------------------------------
# 1. Report-level provenance
# ---------------------------------------------------------------------------

class TestReportProvenance:

    def test_provenance_distinguishes_precomputed_reused_agnes_rss_fallback(self, monkeypatch):
        """Construct actual generate_report flow, verify analysis statistics."""
        import src.report_generator as rg

        call_count = [0]

        def fake_brief(title, content, category="tech", _router=None, _budget=None):
            call_count[0] += 1
            if _router:
                _router.last_result = LLMResult(
                    "Agnes brief " + str(call_count[0]), "agnes", "agnes-2.5-flash",
                )
            return "Agnes brief " + str(call_count[0])

        monkeypatch.setattr(rg, "generate_news_brief", fake_brief)
        monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
        monkeypatch.setattr(rg, "_BRIEF_CACHE", LLMCache())
        monkeypatch.setattr(rg, "_BRIEF_BUDGET", AgnesBudget(max_calls=10, min_interval=0))
        monkeypatch.setattr(rg, "GEMINI_RATE_LIMIT_DELAY", 0)

        intel = _empty_intel()
        intel["tech_trends"] = [
            {"title": "Pre", "url": "https://e.com/1", "category": "C1",
             "starhub": True, "analysis_brief": "already analyzed"},
            {"title": "Reused", "url": "https://e.com/2", "category": "C2",
             "starhub": True, "summary_cn": "existing chinese"},
            {"title": "Agnes", "url": "https://e.com/3", "category": "C3",
             "starhub": True, "summary": "RSS content here"},
            {"title": "Fallback", "url": "https://e.com/4", "category": "C4",
             "starhub": True, "summary": "", "content": ""},
        ]
        intel["_provenance"] = {"starhub": {
            "enabled": True, "snapshot_sources": 1, "snapshot_items": 4,
            "adapted_items": 4, "routed": {"tech_trends": 4},
        }}

        rg.generate_report(intel, "2026-01-01")

        analysis = intel["_provenance"]["starhub"]["analysis"]
        assert analysis.get("precomputed") == 1
        assert analysis.get("reused") == 1
        assert analysis.get("agnes") == 1
        assert analysis.get("rss_fallback") == 1

    def test_gemini_stage_when_router_returns_gemini(self, monkeypatch):
        """When router falls back to gemini, stage should be 'gemini'."""
        import src.report_generator as rg

        def fake_brief(title, content, category="tech", _router=None, _budget=None):
            if _router:
                _router.last_result = LLMResult("Gemini brief", "gemini", "gemini-2.0-flash")
            return "Gemini brief"

        monkeypatch.setattr(rg, "generate_news_brief", fake_brief)
        monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
        monkeypatch.setattr(rg, "_BRIEF_CACHE", LLMCache())
        monkeypatch.setattr(rg, "_BRIEF_BUDGET", AgnesBudget(max_calls=10, min_interval=0))
        monkeypatch.setattr(rg, "GEMINI_RATE_LIMIT_DELAY", 0)

        intel = _empty_intel()
        intel["tech_trends"] = [
            {"title": "Gemini", "url": "https://e.com/1", "category": "C1",
             "starhub": True, "summary": "RSS content"},
        ]
        intel["_provenance"] = {"starhub": {
            "enabled": True, "snapshot_sources": 1, "snapshot_items": 1,
            "adapted_items": 1, "routed": {"tech_trends": 1},
        }}

        rg.generate_report(intel, "2026-01-01")

        analysis = intel["_provenance"]["starhub"]["analysis"]
        assert analysis.get("gemini") == 1

    def test_provenance_selected_and_fallback_counts(self, monkeypatch):
        """provenance must include selected_count and fallback_count."""
        import src.report_generator as rg

        monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
        monkeypatch.setattr(rg, "_BRIEF_CACHE", LLMCache())
        monkeypatch.setattr(rg, "GEMINI_RATE_LIMIT_DELAY", 0)
        monkeypatch.setattr(rg, "generate_news_brief", lambda *a, **k: "")

        intel = _empty_intel()
        intel["tech_trends"] = [
            {"title": "A", "url": "https://e.com/1", "category": "C1",
             "starhub": True, "analysis_brief": "existing"},
            {"title": "B", "url": "https://e.com/2", "category": "C2",
             "starhub": True, "summary": "content"},
        ]
        intel["_provenance"] = {"starhub": {
            "enabled": True, "snapshot_sources": 1, "snapshot_items": 2,
            "adapted_items": 2, "routed": {"tech_trends": 2},
        }}

        rg.generate_report(intel, "2026-01-01")

        prov = intel["_provenance"]["starhub"]
        assert prov.get("selected_count") == 2
        assert prov.get("fallback_count") >= 1


# ---------------------------------------------------------------------------
# 2. Item-level fields
# ---------------------------------------------------------------------------

class TestItemLevelFields:

    def test_llm_success_sets_provider_model_cached(self, monkeypatch):
        """After LLM success, item must have _provider, _model, _cached=False."""
        import src.report_generator as rg

        def fake_brief(title, content, category="tech", _router=None, _budget=None):
            if _router:
                _router.last_result = LLMResult("Agnes brief", "agnes", "agnes-2.5-flash")
            return "Agnes brief"

        monkeypatch.setattr(rg, "generate_news_brief", fake_brief)
        monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
        monkeypatch.setattr(rg, "_BRIEF_CACHE", LLMCache())
        monkeypatch.setattr(rg, "_BRIEF_BUDGET", AgnesBudget(max_calls=10, min_interval=0))

        item = {"title": "T", "url": "https://e.com", "starhub": True, "summary": "content"}
        rg._signal_brief(item, "tech")

        assert item.get("_provider") == "agnes"
        assert item.get("_model") == "agnes-2.5-flash"
        assert item.get("_cached") is False
        assert item.get("_analysis_stage") == "agnes"

    def test_cache_hit_sets_cached_true(self, monkeypatch):
        """Cache hit must set _cached=True, stage='reused'."""
        import src.report_generator as rg

        cache = LLMCache()
        monkeypatch.setattr(rg, "_BRIEF_CACHE", cache)
        monkeypatch.setattr(rg, "AGNES_MODEL", "agnes-m")
        monkeypatch.setattr(rg, "GEMINI_MODEL", "gemini-m")
        monkeypatch.setattr(rg, "LLM_AVAILABLE", True)

        item = {"title": "cached content", "url": "https://e.com",
                "starhub": True, "summary": "cached content", "content": "cached content"}
        request_content = "\n".join(("cached content", "tech", "cached content"))
        key = cache_key("agnes", "agnes-m", "news_brief", "v1", request_content)
        cache.put(key, LLMResult("Cached text", "agnes", "agnes-m"))

        result = rg._signal_brief(item, "tech")

        assert result == "Cached text"
        assert item.get("_cached") is True
        assert item.get("_provider") == "agnes"
        assert item.get("_model") == "agnes-m"
        assert item.get("_analysis_stage") == "reused"

    def test_budget_exhausted_sets_failure_reason(self, monkeypatch):
        """Budget exhausted must set _failure_reason='budget_exhausted'."""
        import src.report_generator as rg

        monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
        monkeypatch.setattr(rg, "_BRIEF_BUDGET", AgnesBudget(max_calls=0, min_interval=0))
        monkeypatch.setattr(rg, "generate_news_brief", lambda *a, **k: "")

        item = {"title": "T", "url": "https://e.com", "starhub": True,
                "summary": "RSS summary", "content": "content"}
        rg._signal_brief(item, "tech")

        assert item.get("_analysis_stage") == "rss_fallback"
        assert item.get("_failure_reason") == "budget_exhausted"

    def test_reused_chinese_field_sets_stage_reused(self, monkeypatch):
        """summary_cn reuse must set stage='reused', not 'precomputed'."""
        import src.report_generator as rg

        monkeypatch.setattr(rg, "generate_news_brief",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))

        item = {"summary_cn": "existing chinese", "summary": "English summary", "starhub": True}
        result = rg._signal_brief(item, "tech")

        assert result == "existing chinese"
        assert item.get("_analysis_stage") == "reused"


# ---------------------------------------------------------------------------
# 3. Structured logging
# ---------------------------------------------------------------------------

class TestStructuredLogging:

    def test_report_logs_provenance_with_safe_fields(self, monkeypatch, caplog):
        """Report generation must log provenance with safe fields."""
        import src.report_generator as rg

        monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
        monkeypatch.setattr(rg, "_BRIEF_CACHE", LLMCache())

        intel = _empty_intel()
        intel["tech_trends"] = [
            {"title": "T", "url": "https://e.com", "category": "C",
             "starhub": True, "analysis_brief": "existing"},
        ]
        intel["_provenance"] = {"starhub": {
            "enabled": True, "snapshot_sources": 1, "snapshot_items": 1,
            "adapted_items": 1, "routed": {"tech_trends": 1},
        }}

        with caplog.at_level(logging.INFO, logger="src.report_generator"):
            rg.generate_report(intel, "2026-01-01")

        provenance_logs = [r.message for r in caplog.records
                           if "PROVENANCE" in r.message]
        assert len(provenance_logs) >= 1
        log_text = provenance_logs[0]
        assert "selected_count" in log_text
        assert "fallback_count" in log_text

    def test_report_log_never_contains_api_keys(self, monkeypatch, caplog):
        """Log output must never contain API keys."""
        import src.report_generator as rg

        monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
        monkeypatch.setattr(rg, "_BRIEF_CACHE", LLMCache())
        monkeypatch.setattr(rg, "AGNES_API_KEY", "super-secret-agnes-key-12345")
        monkeypatch.setattr(rg, "GEMINI_API_KEY", "super-secret-gemini-key-67890")

        intel = _empty_intel()
        intel["tech_trends"] = [
            {"title": "T", "url": "https://e.com", "category": "C",
             "starhub": True, "analysis_brief": "existing"},
        ]
        intel["_provenance"] = {"starhub": {
            "enabled": True, "snapshot_sources": 1, "snapshot_items": 1,
            "adapted_items": 1, "routed": {"tech_trends": 1},
        }}

        with caplog.at_level(logging.DEBUG, logger="src.report_generator"):
            rg.generate_report(intel, "2026-01-01")

        for record in caplog.records:
            assert "super-secret-agnes-key-12345" not in record.message
            assert "super-secret-gemini-key-67890" not in record.message


# ---------------------------------------------------------------------------
# 4. CI workflow
# ---------------------------------------------------------------------------

class TestCIWorkflow:

    _WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "daily-report.yml"

    def test_workflow_has_required_env_vars(self):
        """daily-report.yml Generate step must have LLM_PROVIDER etc."""
        with open(self._WORKFLOW, encoding="utf-8") as f:
            content = f.read()

        required = [
            "LLM_PROVIDER",
            "LLM_FALLBACK_PROVIDER",
            "AGNES_MODEL",
            "AGNES_MAX_CALLS_PER_RUN",
            "AGNES_MIN_INTERVAL",
            "AGNES_CONCURRENCY",
        ]
        for key in required:
            assert key in content, "Missing env key: " + key

        assert "agnes-2.5-flash" in content

    def test_workflow_uses_secrets_for_api_keys(self):
        """API keys must use secrets, no hardcoding."""
        with open(self._WORKFLOW, encoding="utf-8") as f:
            content = f.read()

        assert "secrets.AGNES_API_KEY" in content
        assert "secrets.GEMINI_API_KEY" in content
        assert "sk-ant-" not in content
        assert "AIzaSy" not in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
