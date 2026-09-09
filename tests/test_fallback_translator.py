"""Fallback stubs must accept the same keyword arguments as the real translator.

When gemini_translator import fails, report_generator defines fallback stubs.
Task 5 call-sites pass _router and _budget keywords; if stubs don't accept
them, a TypeError would be raised at runtime.

These tests force the fallback path by blocking gemini_translator import,
then reloading report_generator to exercise the except branch.
"""
import importlib
import sys
import pytest


@pytest.fixture
def rg_fallback(monkeypatch):
    """Force gemini_translator import failure and reload report_generator.

    Returns the reloaded module (with fallback stubs active).
    After the test, restores original module state.
    """
    # Save original functions that may leak through reload
    import src.report_generator as rg
    saved = {}
    for name in ("translate_to_chinese", "summarize_blog_article",
                 "generate_brief", "generate_news_brief", "expand_product_tagline"):
        saved[name] = getattr(rg, name, None)

    # Block gemini_translator import to trigger except branch
    monkeypatch.setitem(sys.modules, "src.utils.gemini_translator", None)

    # Reload report_generator so the fallback stubs get defined
    reloaded = importlib.reload(rg)

    # For names that the fallback block does NOT define, remove leaked references
    # so we can detect their absence. The fallback block defines:
    #   translate_to_chinese, summarize_blog_article, generate_brief, generate_news_brief
    # but currently NOT expand_product_tagline.
    # We check after reload whether each name was redefined by fallback.
    # If a function is the SAME object as the saved real one, the fallback
    # didn't define it → delete it to expose the gap.
    for name, original in saved.items():
        current = getattr(reloaded, name, None)
        if current is original:
            # Fallback didn't redefine this → remove to expose the gap
            try:
                delattr(reloaded, name)
            except AttributeError:
                pass

    yield reloaded

    # Restore: put back originals and reload with real module available
    for name, original in saved.items():
        if original is not None:
            setattr(reloaded, name, original)
    sys.modules.pop("src.utils.gemini_translator", None)
    importlib.reload(reloaded)


class TestFallbackStubsAcceptRouterBudget:
    """Each fallback stub must accept _router=None and _budget=None keywords."""

    def test_translate_to_chinese_accepts_router_budget(self, rg_fallback):
        result = rg_fallback.translate_to_chinese("hello world", _router="fake", _budget="fake")
        assert isinstance(result, str)

    def test_summarize_blog_article_accepts_router_budget(self, rg_fallback):
        result = rg_fallback.summarize_blog_article("some content", _router="fake", _budget="fake")
        assert isinstance(result, str)

    def test_generate_brief_accepts_router_budget(self, rg_fallback):
        result = rg_fallback.generate_brief("some content", _router="fake", _budget="fake")
        assert isinstance(result, str)

    def test_generate_news_brief_accepts_router_budget(self, rg_fallback):
        result = rg_fallback.generate_news_brief("title", "content", _router="fake", _budget="fake")
        assert isinstance(result, str)

    def test_expand_product_tagline_exists_as_fallback(self, rg_fallback):
        """expand_product_tagline must exist even when gemini_translator is missing."""
        assert hasattr(rg_fallback, "expand_product_tagline"), \
            "expand_product_tagline has no fallback stub in report_generator"

    def test_expand_product_tagline_accepts_router_budget(self, rg_fallback):
        if not hasattr(rg_fallback, "expand_product_tagline"):
            pytest.fail("expand_product_tagline fallback stub is missing entirely")
        result = rg_fallback.expand_product_tagline("name", "tagline", _router="fake", _budget="fake")
        assert isinstance(result, str)


class TestFallbackStubsPreserveReturnSemantics:
    """Fallback stubs must keep their original return behaviour."""

    def test_translate_short_text_unchanged(self, rg_fallback):
        assert rg_fallback.translate_to_chinese("hello") == "hello"

    def test_translate_long_text_truncated(self, rg_fallback):
        long_text = "a" * 200
        result = rg_fallback.translate_to_chinese(long_text, max_chars=100)
        assert result == "a" * 100 + "..."

    def test_summarize_returns_empty(self, rg_fallback):
        assert rg_fallback.summarize_blog_article("content") == ""

    def test_generate_brief_returns_empty(self, rg_fallback):
        assert rg_fallback.generate_brief("content") == ""

    def test_generate_news_brief_returns_empty(self, rg_fallback):
        assert rg_fallback.generate_news_brief("title") == ""

    def test_expand_product_tagline_returns_empty(self, rg_fallback):
        if not hasattr(rg_fallback, "expand_product_tagline"):
            pytest.fail("expand_product_tagline fallback stub is missing")
        assert rg_fallback.expand_product_tagline("name", "tagline") == ""
