"""
config.validate() warning logic tests.

Verify LLM provider missing-key warning behavior:
- Preserve XAI / GITHUB warnings
- Agnes primary provider missing key -> clear disabled/fallback warning
- Gemini primary provider missing key -> corresponding warning
- Both keys missing -> RSS fallback only warning
- No unconditional 'report generation will fail'
"""
import pytest
from src.config import IntelConfig


def _make_config(**overrides):
    defaults = dict(
        gemini_api_key=None,
        xai_api_key=None,
        github_token=None,
        agnes_api_key=None,
        llm_provider="agnes",
        llm_fallback_provider="gemini",
    )
    defaults.update(overrides)
    return IntelConfig(**defaults)


class TestPreservedWarnings:
    def test_xai_missing_warning(self):
        cfg = _make_config(xai_api_key=None)
        warnings = cfg.validate()
        assert any("XAI_API_KEY" in w for w in warnings)

    def test_github_missing_warning(self):
        cfg = _make_config(github_token=None)
        warnings = cfg.validate()
        assert any("GITHUB_TOKEN" in w for w in warnings)

    def test_xai_present_no_warning(self):
        cfg = _make_config(xai_api_key="xai-xxx")
        warnings = cfg.validate()
        assert not any("XAI_API_KEY" in w for w in warnings)

    def test_github_present_no_warning(self):
        cfg = _make_config(github_token="gh_xxx")
        warnings = cfg.validate()
        assert not any("GITHUB_TOKEN" in w for w in warnings)


class TestAgnesPrimaryProvider:
    def test_agnes_key_only_no_gemini_no_report_fail_warning(self):
        cfg = _make_config(
            agnes_api_key="agnes-xxx",
            gemini_api_key=None,
            llm_provider="agnes",
            llm_fallback_provider="gemini",
        )
        warnings = cfg.validate()
        assert not any("report generation will fail" in w for w in warnings)
        assert not any("report generation will fail" in w.lower() for w in warnings)

    def test_agnes_missing_with_gemini_fallback_mentions_fallback(self):
        cfg = _make_config(
            agnes_api_key=None,
            gemini_api_key="gemini-xxx",
            llm_provider="agnes",
            llm_fallback_provider="gemini",
        )
        warnings = cfg.validate()
        agnes_warnings = [w for w in warnings if "agnes" in w.lower() or "AGNES" in w]
        assert len(agnes_warnings) >= 1, f"Expected Agnes warning, got: {warnings}"
        assert any("fallback" in w.lower() or "gemini" in w.lower() for w in agnes_warnings)

    def test_agnes_missing_no_fallback_mentions_rss(self):
        cfg = _make_config(
            agnes_api_key=None,
            gemini_api_key=None,
            llm_provider="agnes",
            llm_fallback_provider="gemini",
        )
        warnings = cfg.validate()
        assert any("rss" in w.lower() for w in warnings), f"Expected RSS mention in warnings: {warnings}"


class TestGeminiPrimaryProvider:
    def test_gemini_primary_missing_key_warning(self):
        cfg = _make_config(
            gemini_api_key=None,
            agnes_api_key=None,
            llm_provider="gemini",
            llm_fallback_provider="agnes",
        )
        warnings = cfg.validate()
        gemini_warnings = [w for w in warnings if "gemini" in w.lower() or "GEMINI" in w]
        assert len(gemini_warnings) >= 1, f"Expected Gemini warning, got: {warnings}"

    def test_gemini_primary_missing_with_agnes_fallback(self):
        cfg = _make_config(
            gemini_api_key=None,
            agnes_api_key="agnes-xxx",
            llm_provider="gemini",
            llm_fallback_provider="agnes",
        )
        warnings = cfg.validate()
        assert any("fallback" in w.lower() or "agnes" in w.lower() for w in warnings)


class TestNoProviderKeys:
    def test_no_keys_rss_fallback_warning(self):
        cfg = _make_config(
            agnes_api_key=None,
            gemini_api_key=None,
            llm_provider="agnes",
            llm_fallback_provider="gemini",
        )
        warnings = cfg.validate()
        assert any("rss" in w.lower() for w in warnings), f"Expected RSS fallback warning, got: {warnings}"

    def test_no_keys_no_report_fail_warning(self):
        cfg = _make_config(
            agnes_api_key=None,
            gemini_api_key=None,
            llm_provider="agnes",
            llm_fallback_provider="gemini",
        )
        warnings = cfg.validate()
        assert not any("report generation will fail" in w for w in warnings)


class TestAllKeysPresent:
    def test_all_keys_no_llm_warnings(self):
        cfg = _make_config(
            agnes_api_key="agnes-xxx",
            gemini_api_key="gemini-xxx",
            xai_api_key="xai-xxx",
            github_token="gh_xxx",
            llm_provider="agnes",
            llm_fallback_provider="gemini",
        )
        warnings = cfg.validate()
        llm_warnings = [w for w in warnings if any(
            kw in w.lower() for kw in ["agnes", "gemini", "llm", "rss fallback"]
        )]
        assert len(llm_warnings) == 0, f"Unexpected LLM warnings: {llm_warnings}"


class TestConfigFieldsPreserved:
    def test_all_fields_exist(self):
        cfg = _make_config()
        assert hasattr(cfg, "gemini_api_key")
        assert hasattr(cfg, "agnes_api_key")
        assert hasattr(cfg, "xai_api_key")
        assert hasattr(cfg, "github_token")
        assert hasattr(cfg, "llm_provider")
        assert hasattr(cfg, "llm_fallback_provider")
        assert hasattr(cfg, "gemini_api_url")
        assert hasattr(cfg, "gemini_model")
        assert hasattr(cfg, "agnes_api_url")
        assert hasattr(cfg, "agnes_model")

    def test_validate_returns_list(self):
        cfg = _make_config()
        result = cfg.validate()
        assert isinstance(result, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
