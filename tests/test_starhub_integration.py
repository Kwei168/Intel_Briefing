"""StarHub -> Intel Briefing regression tests."""
import importlib.util


def _empty_intel():
    return {key: [] for key in (
        "tech_trends", "capital_flow", "product_gems", "community",
        "research", "social", "insights",
    )}


def test_bridge_keeps_all_items_for_downstream_selection():
    from src.sensors.starhub_bridge import adapt_to_intel

    snapshot = {"sources": [{
        "cat": "tech", "name": "Test Source", "url": "https://example.com/feed",
        "items": [{"t": f"Item {i}", "u": f"https://example.com/{i}"} for i in range(60)],
    }]}
    adapted = adapt_to_intel(snapshot)
    assert len(adapted["tech_trends"]) == 60


def test_starhub_routing_uses_source_semantics():
    from src.intel_collector import _route_starhub_item

    assert _route_starhub_item({"category": "V2EX 创意", "source_category": "dev"}) == "community"
    assert _route_starhub_item({"category": "arXiv AI", "source_category": "ai"}) == "research"
    assert _route_starhub_item({"category": "36氪", "source_category": "wechat"}) == "capital_flow"


def test_report_selection_preserves_source_diversity():
    from src.report_generator import _select_diverse_items

    items = [
        {"title": f"TechCrunch {i}", "url": f"https://tc.example/{i}", "category": "TechCrunch"}
        for i in range(10)
    ] + [
        {"title": f"StarHub {i}", "url": f"https://starhub.example/{i}", "category": "StarHub Source", "starhub": True}
        for i in range(3)
    ]
    selected = _select_diverse_items(items, 10)
    assert any(item.get("starhub") for item in selected)
    assert sum(item.get("category") == "TechCrunch" for item in selected) <= 2


def test_report_renders_starhub_analysis_brief():
    from src.report_generator import generate_report

    intel = _empty_intel()
    intel["tech_trends"] = [{
        "title": "StarHub signal", "url": "https://example.com/signal",
        "category": "StarHub Source", "starhub": True,
        "summary": "raw feed summary", "analysis_brief": "分析后的中文情报摘要",
    }]
    report = generate_report(intel, "2026-01-01")
    assert "分析后的中文情报摘要" in report


def test_report_uses_available_agnes_when_gemini_key_missing(monkeypatch):
    import src.report_generator as report_generator
    monkeypatch.setattr(report_generator, "GEMINI_AVAILABLE", False)
    monkeypatch.setattr(report_generator, "LLM_AVAILABLE", True)
    monkeypatch.setattr(report_generator, "generate_news_brief", lambda *a, **k: "Agnes brief")
    intel = _empty_intel()
    intel["tech_trends"] = [{"title": "Signal", "url": "https://example.com", "starhub": True, "summary": "Enough source content here."}]
    assert "Agnes brief" in report_generator.generate_report(intel, "2026-01-01")


def test_pages_template_decodes_unicode_literals():
    spec = importlib.util.spec_from_file_location("build_pages", r"E:\Intel_Briefing\.github\build_pages.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    html = module.render_page("2026-01-01", "# 测试")
    assert "\\u65e5" not in html
    assert "日报列表" in html
    assert "每日情报日报" in html


def test_product_hunt_atom_parser_returns_products():
    from src.sensors.product_hunt import _parse_rss_products

    xml = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Test Product</title><link rel="alternate" href="https://www.producthunt.com/posts/test-product"/>
      <summary>A useful product</summary><published>2026-01-01T00:00:00Z</published></entry>
    </feed>"""
    products = _parse_rss_products(xml, 10)
    assert len(products) == 1
    assert products[0].name == "Test Product"
    assert products[0].url.endswith("test-product")


def test_report_records_starhub_selection_and_analysis_trace():
    from src.report_generator import generate_report

    intel = _empty_intel()
    intel["tech_trends"] = [{
        "title": "Traced StarHub signal",
        "url": "https://example.com/traced",
        "category": "StarHub Source",
        "starhub": True,
        "summary": "source summary",
        "analysis_brief": "已筛选的分析摘要",
    }]
    intel["_provenance"] = {"starhub": {
        "enabled": True, "snapshot_sources": 1, "snapshot_items": 1,
        "adapted_items": 1, "routed": {"tech_trends": 1},
    }}

    report = generate_report(intel, "2026-01-01")

    trace = intel["_provenance"]["starhub"]
    assert trace["selected"]["tech_trends"] == 1
    assert trace["analysis"]["precomputed"] == 1
    assert "分析溯源" in report


def test_signal_brief_precomputed_does_not_call_provider(monkeypatch):
    import src.report_generator as report_generator

    item = {"analysis_brief": "已有分析", "summary": "RSS 原文", "starhub": True}
    monkeypatch.setattr(report_generator, "generate_news_brief", lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider must not be called")))

    assert report_generator._signal_brief(item, "tech") == "已有分析"
    assert item["_analysis_stage"] == "precomputed"


def test_signal_brief_reuses_existing_chinese_fields_without_provider(monkeypatch):
    import src.report_generator as report_generator

    for field in ("summary_cn", "translation"):
        item = {field: "已有中文摘要", "summary": "English RSS summary", "starhub": True}
        monkeypatch.setattr(report_generator, "generate_news_brief", lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider must not be called")))

        assert report_generator._signal_brief(item, "tech") == "已有中文摘要"
        assert item["analysis_brief"] == "已有中文摘要"


def test_signal_brief_budget_exhaustion_uses_rss_summary(monkeypatch):
    import src.report_generator as report_generator
    from src.utils.llm_provider import AgnesBudget

    item = {"title": "Signal", "summary": "RSS summary", "content": "longer content", "starhub": True}
    monkeypatch.setattr(report_generator, "LLM_AVAILABLE", True)
    monkeypatch.setattr(report_generator, "_BRIEF_BUDGET", AgnesBudget(max_calls=0, min_interval=0))
    monkeypatch.setattr(report_generator, "generate_news_brief", lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider must not be called")))

    assert report_generator._signal_brief(item, "tech") == "RSS summary"
    assert item["_analysis_stage"] == "rss_fallback"


def test_report_calls_provider_only_for_selected_starhub_items(monkeypatch):
    import src.report_generator as report_generator

    calls = []
    monkeypatch.setattr(report_generator, "LLM_AVAILABLE", True)
    def fake_brief(title, content, category="tech", **kwargs):
        calls.append(title)
        return "生成摘要"
    monkeypatch.setattr(report_generator, "generate_news_brief", fake_brief)

    intel = _empty_intel()
    intel["tech_trends"] = [
        {"title": "StarHub selected", "url": "https://example.com/s", "category": "StarHub", "starhub": True, "summary": "RSS summary"},
        {"title": "Other source", "url": "https://example.com/o", "category": "Other", "summary": "Other summary"},
    ]

    report_generator.generate_report(intel, "2026-01-01")

    assert calls == ["StarHub selected"]


# ---- Task 5: unified research / insights / product paths ----

def test_research_brief_and_detail_use_shared_router(monkeypatch):
    """Research items must go through the shared Router, not direct GEMINI_API_KEY."""
    import src.report_generator as rg

    calls = {"generate_brief": [], "translate": []}

    def fake_brief(content, category="general", _router=None, _budget=None):
        calls["generate_brief"].append({"router": _router, "budget": _budget})
        return "研究简报"

    def fake_translate(text, max_chars=100, _router=None, _budget=None):
        calls["translate"].append({"router": _router, "budget": _budget})
        return "研究详情"

    monkeypatch.setattr(rg, "generate_brief", fake_brief)
    monkeypatch.setattr(rg, "translate_to_chinese", fake_translate)
    monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
    monkeypatch.setattr(rg, "GEMINI_RATE_LIMIT_DELAY", 0)

    intel = _empty_intel()
    intel["research"] = [{"title": "Paper", "url": "https://arxiv.org/x", "summary": "Some abstract here", "starhub": True}]
    rg.generate_report(intel, "2026-01-01")

    assert len(calls["generate_brief"]) == 1
    assert calls["generate_brief"][0]["router"] is rg._BRIEF_ROUTER
    assert calls["generate_brief"][0]["budget"] is rg._BRIEF_BUDGET
    assert len(calls["translate"]) == 1
    assert calls["translate"][0]["router"] is rg._BRIEF_ROUTER


def test_research_detail_capped_at_1200_chars(monkeypatch):
    """Research detail translation must be capped at 1200 characters."""
    import src.report_generator as rg

    captured_max = {}

    def fake_brief(content, category="general", _router=None, _budget=None):
        return "brief"

    def fake_translate(text, max_chars=100, _router=None, _budget=None):
        captured_max["max_chars"] = max_chars
        return "详情"

    monkeypatch.setattr(rg, "generate_brief", fake_brief)
    monkeypatch.setattr(rg, "translate_to_chinese", fake_translate)
    monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
    monkeypatch.setattr(rg, "GEMINI_RATE_LIMIT_DELAY", 0)

    intel = _empty_intel()
    intel["research"] = [{"title": "Paper", "url": "https://arxiv.org/x", "summary": "Abstract text", "starhub": True}]
    rg.generate_report(intel, "2026-01-01")

    assert captured_max["max_chars"] == 1200


def test_insights_brief_and_detail_use_shared_router(monkeypatch):
    """Insights items must use the shared Router for both brief and detail."""
    import src.report_generator as rg

    calls = []

    def fake_summarize(content, mode="brief", _router=None, _budget=None):
        calls.append({"mode": mode, "router": _router, "budget": _budget})
        return "洞察摘要"

    monkeypatch.setattr(rg, "summarize_blog_article", fake_summarize)
    monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
    monkeypatch.setattr(rg, "JINA_AVAILABLE", False)
    monkeypatch.setattr(rg, "GEMINI_RATE_LIMIT_DELAY", 0)

    intel = _empty_intel()
    intel["insights"] = [{"title": "Blog", "url": "https://example.com/blog", "content": "RSS content " * 20, "starhub": True}]
    rg.generate_report(intel, "2026-01-01")

    assert len(calls) == 2
    assert calls[0]["mode"] == "brief"
    assert calls[0]["router"] is rg._BRIEF_ROUTER
    assert calls[1]["mode"] == "detail"
    assert calls[1]["router"] is rg._BRIEF_ROUTER


def test_insights_jina_failure_falls_back_to_rss_content(monkeypatch):
    """When Jina fails, insights should still use RSS content through the Router."""
    import src.report_generator as rg

    captured_content = []

    def fake_summarize(content, mode="brief", _router=None, _budget=None):
        captured_content.append(content)
        return "降级摘要"

    def fake_jina(url):
        return None  # Jina fails

    monkeypatch.setattr(rg, "summarize_blog_article", fake_summarize)
    monkeypatch.setattr(rg, "fetch_full_content", fake_jina)
    monkeypatch.setattr(rg, "LLM_AVAILABLE", True)
    monkeypatch.setattr(rg, "JINA_AVAILABLE", True)
    monkeypatch.setattr(rg, "GEMINI_RATE_LIMIT_DELAY", 0)

    rss_text = "RSS fallback content " * 20
    intel = _empty_intel()
    intel["insights"] = [{"title": "Blog", "url": "https://example.com/blog", "content": rss_text, "starhub": True}]
    rg.generate_report(intel, "2026-01-01")

    assert len(captured_content) >= 1
    assert rss_text in captured_content[0]


def test_product_expand_tagline_called_when_analysis_brief_missing(monkeypatch):
    """Product items missing analysis_brief should trigger expand_product_tagline via shared budget."""
    import src.report_generator as rg

    calls = []

    def fake_expand(name, tagline, _router=None, _budget=None):
        calls.append({"name": name, "router": _router, "budget": _budget})
        return "产品定位描述"

    monkeypatch.setattr(rg, "expand_product_tagline", fake_expand)
    monkeypatch.setattr(rg, "LLM_AVAILABLE", True)

    intel = _empty_intel()
    intel["product_gems"] = [{"title": "NewProduct", "url": "https://producthunt.com/p/new", "tagline": "A great tool", "starhub": True}]
    rg.generate_report(intel, "2026-01-01")

    assert len(calls) == 1
    assert calls[0]["name"] == "NewProduct"
    assert calls[0]["router"] is rg._BRIEF_ROUTER


def test_product_expand_tagline_skipped_when_analysis_brief_exists(monkeypatch):
    """Product items with existing analysis_brief must NOT call expand_product_tagline."""
    import src.report_generator as rg

    def fake_expand(name, tagline, _router=None, _budget=None):
        raise AssertionError("expand_product_tagline must not be called when analysis_brief exists")

    monkeypatch.setattr(rg, "expand_product_tagline", fake_expand)
    monkeypatch.setattr(rg, "LLM_AVAILABLE", True)

    intel = _empty_intel()
    intel["product_gems"] = [{"title": "Product", "url": "https://ph.example/p", "tagline": "tagline", "analysis_brief": "已有定位", "starhub": True}]
    report = rg.generate_report(intel, "2026-01-01")

    assert "已有定位" in report


# ---- Task 6: pass through precomputed snapshot fields in bridge mapping ----

def test_adapt_to_intel_passes_through_precomputed_fields():
    """Snapshot item 已有的 summary_cn / translation / analysis_brief 必须原样透传。"""
    from src.sensors.starhub_bridge import adapt_to_intel

    snapshot = {"sources": [{
        "cat": "tech", "name": "StarHub Source", "url": "https://example.com/feed",
        "items": [
            {
                "t": "Full fields", "u": "https://example.com/1", "s": "raw feed summary",
                "summary_cn": "已有中文摘要", "translation": "已有整篇翻译",
                "analysis_brief": "已有分析简报",
            },
            {
                "t": "Partial fields", "u": "https://example.com/2", "s": "raw summary",
                "summary_cn": "只有中文摘要",
            },
        ],
    }]}

    adapted = adapt_to_intel(snapshot)

    items = adapted["tech_trends"]
    assert len(items) == 2
    assert items[0]["summary_cn"] == "已有中文摘要"
    assert items[0]["translation"] == "已有整篇翻译"
    assert items[0]["analysis_brief"] == "已有分析简报"
    assert items[1]["summary_cn"] == "只有中文摘要"
    assert "translation" not in items[1]
    assert "analysis_brief" not in items[1]


def test_adapt_to_intel_empty_precomputed_fields_do_not_pollute_output():
    """缺失或空值字段不得写入适配结果；summary/content 语义保持不变。"""
    from src.sensors.starhub_bridge import adapt_to_intel

    snapshot = {"sources": [{
        "cat": "tech", "name": "StarHub Source", "url": "https://example.com/feed",
        "items": [
            {
                "t": "Empty values", "u": "https://example.com/1", "s": "raw summary text",
                "summary_cn": "", "translation": None, "analysis_brief": "   ",
            },
            {"t": "No extra fields", "u": "https://example.com/2", "s": "raw summary text"},
        ],
    }]}

    adapted = adapt_to_intel(snapshot)

    items = adapted["tech_trends"]
    assert len(items) == 2
    for item in items:
        assert item["summary"] == "raw summary text"
        assert item["content"] == "raw summary text"
        assert "summary_cn" not in item
        assert "translation" not in item
        assert "analysis_brief" not in item


def test_adapt_to_intel_field_passthrough_keeps_count_and_routing():
    """透传不得改变全量 item 数量、栏目路由与已有字段语义。"""
    from src.sensors.starhub_bridge import adapt_to_intel

    snapshot = {"sources": [{
        "cat": "horizon", "name": "AI Source", "url": "https://example.com/feed",
        "items": [
            {"t": f"Item {i}", "u": f"https://example.com/{i}", "s": f"summary {i}",
             "analysis_brief": f"预分析 {i}"}
            for i in range(60)
        ],
    }]}

    adapted = adapt_to_intel(snapshot)

    items = adapted["research"]
    assert len(items) == 60
    assert all(item["analysis_brief"] == f"预分析 {i}" for i, item in enumerate(items))
    assert all(item["summary"] == f"summary {i}" for i, item in enumerate(items))
    assert all(item["summary"] == item["content"] for item in items)
    assert all(item["category"] == "AI Source" for item in items)
    assert all(item["source_category"] == "horizon" for item in items)
    assert all(item["starhub"] for item in items)
