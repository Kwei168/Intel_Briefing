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
