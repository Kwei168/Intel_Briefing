"""
Anti-Hallucination Tests — 验证防幻觉机制。
核心断言：Grok fallback 产生的猜测 URL 不能作为可点击 markdown 链接进入最终报告。
"""


def test_grok_fallback_not_clickable():
    """Grok 猜测的 PH URL 不应渲染成 markdown 可点击链接。"""
    from src.report_generator import generate_report
    intel = {
        "tech_trends": [], "capital_flow": [], "community": [],
        "research": [], "social": [], "insights": [],
        "xhs_directives": [],
        "product_gems": [{
            "title": "FakeProduct",
            "url": "https://www.producthunt.com/posts/fakeproduct",
            "heat": "100 votes",
            "tagline": "A fake product for testing",
            "topics": ["grok-fallback"],
        }],
    }
    report = generate_report(intel, "2026-01-01")

    # Grok fallback URL 不应作为 markdown 链接出现
    assert "[FakeProduct](https://www.producthunt.com/posts/fakeproduct)" not in report
    # 产品标题应该出现在报告中
    assert "FakeProduct" in report
    # 应该有未验证标记
    assert "未验证" in report


def test_verified_ph_url_is_clickable():
    """正常 PH API 返回的 URL 应正常渲染为 markdown 链接。"""
    from src.report_generator import generate_report
    intel = {
        "tech_trends": [], "capital_flow": [], "community": [],
        "research": [], "social": [], "insights": [],
        "xhs_directives": [],
        "product_gems": [{
            "title": "RealProduct",
            "url": "https://www.producthunt.com/posts/realproduct",
            "heat": "200 votes",
            "tagline": "A real product",
            "topics": ["ai", "developer-tools"],
        }],
    }
    report = generate_report(intel, "2026-01-01")
    assert "[RealProduct](https://www.producthunt.com/posts/realproduct)" in report
    assert "未验证" not in report


def test_generate_news_brief_junk_recursion_guard(monkeypatch):
    """如果 Gemini 持续返回 [JUNK]，generate_news_brief 必须停止递归而不是无限烧 API。"""
    from src.utils import gemini_translator as gt

    call_count = {"n": 0}

    class _FakeResp:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "[JUNK] some garbage"}]}}]}

    def _fake_post(*args, **kwargs):
        call_count["n"] += 1
        return _FakeResp()

    monkeypatch.setattr(gt.httpx, "post", _fake_post)
    monkeypatch.setattr(gt, "GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(gt, "AGNES_API_KEY", None, raising=False)

    result = gt.generate_news_brief("Fake Title", "some real content " * 5)

    # 最多 2 次调用（首次 + 1 次降级），不能无限递归
    assert call_count["n"] <= 2, f"递归保护失败：API 被调用了 {call_count['n']} 次"
    # JUNK 终态返回空字符串
    assert result == ""
