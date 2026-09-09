"""
LLM Provider 契约测试.

测试 src.utils.llm_provider 模块的 Provider 契约:
- AgnesProvider: OpenAI-compatible payload, 解析 choices[0].message.content
- GeminiProvider: 解析 candidates[0].content.parts[0].text
- LLMRouter: Agnes 优先, 429 时 fallback 到 Gemini
- 双 Provider 全部失败时抛出 AllProvidersFailed (继承 LLMProviderError)
- LLMResult: 统一返回类型, 含 text/provider/model/cached/finish_reason
- EmptyResponseError / RateLimitError / ProviderError 精确分类

使用 fake httpx transport, 不访问真实网络, 不使用真实密钥.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

import httpx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_agnes_response(content, status_code=200, finish_reason="stop"):
    """构造 Agnes (OpenAI-compatible) 假响应."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]})
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status_code} error",
            request=MagicMock(),
            response=resp,
        )
    resp.json.return_value = {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
    }
    return resp


def _fake_gemini_response(text, status_code=200, finish_reason="STOP"):
    """构造 Gemini 假响应."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish_reason}]})
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status_code} error",
            request=MagicMock(),
            response=resp,
        )
    resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish_reason}],
    }
    return resp


# ---------------------------------------------------------------------------
# Agnes Provider 契约
# ---------------------------------------------------------------------------

class TestAgnesProvider:
    """Agnes OpenAI-compatible Provider 契约."""

    def test_agnes_payload_contains_required_fields(self):
        """Agnes 请求 payload 必须包含 model / messages / max_tokens / temperature
        以及 chat_template_kwargs.enable_thinking=False."""
        from src.utils.llm_provider import AgnesProvider

        provider = AgnesProvider(
            base_url="https://agnes.example.com/v1",
            api_key="fake-agnes-key",
            model="agnes-test-model",
        )

        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json", {})
            return _fake_agnes_response("你好世界")

        with patch("httpx.post", side_effect=fake_post):
            result = provider.chat("测试提示")

        payload = captured["json"]
        assert "model" in payload
        assert "messages" in payload
        assert "max_tokens" in payload
        assert "temperature" in payload
        assert payload["chat_template_kwargs"]["enable_thinking"] is False
        # LLMResult assertions
        assert result.text == "你好世界"
        assert result.provider == "agnes"
        assert result.model == "agnes-test-model"
        assert result.cached is False
        assert result.finish_reason == "stop"

    def test_agnes_preserves_complete_endpoint(self):
        from src.utils.llm_provider import AgnesProvider
        u="https://apihub.agnes-ai.com/v1/chat/completions"
        x=AgnesProvider(u,"k","m")
        with patch("httpx.post",return_value=_fake_agnes_response("ok")) as post:
            x.chat("p")
        assert post.call_args.args[0]==u

    def test_agnes_parses_choices_message_content(self):
        """Agnes 必须解析 choices[0].message.content."""
        from src.utils.llm_provider import AgnesProvider

        provider = AgnesProvider(
            base_url="https://agnes.example.com/v1",
            api_key="fake-key",
            model="m",
        )

        with patch("httpx.post", return_value=_fake_agnes_response("解析结果OK")):
            result = provider.chat("prompt")
            assert result.text == "解析结果OK"
            assert result.provider == "agnes"

    def test_agnes_empty_content_raises_empty_response_error(self):
        """Agnes 返回空 content 时, Provider 应抛出 EmptyResponseError."""
        from src.utils.llm_provider import AgnesProvider, EmptyResponseError, LLMProviderError

        provider = AgnesProvider(
            base_url="https://agnes.example.com/v1",
            api_key="fake-key",
            model="m",
        )

        with patch("httpx.post", return_value=_fake_agnes_response("")):
            with pytest.raises(EmptyResponseError):
                provider.chat("prompt")

    def test_agnes_429_raises_rate_limit_error(self):
        """Agnes HTTP 429 应抛出 RateLimitError."""
        from src.utils.llm_provider import AgnesProvider, RateLimitError

        provider = AgnesProvider(
            base_url="https://agnes.example.com/v1",
            api_key="fake-key",
            model="m",
        )

        with patch("httpx.post", return_value=_fake_agnes_response("", status_code=429)):
            with pytest.raises(RateLimitError):
                provider.chat("prompt")

    def test_agnes_500_raises_provider_error(self):
        """Agnes HTTP 500 应抛出 ProviderError."""
        from src.utils.llm_provider import AgnesProvider, ProviderError

        provider = AgnesProvider(
            base_url="https://agnes.example.com/v1",
            api_key="fake-key",
            model="m",
        )

        with patch("httpx.post", return_value=_fake_agnes_response("", status_code=500)):
            with pytest.raises(ProviderError):
                provider.chat("prompt")


# ---------------------------------------------------------------------------
# Gemini Provider 契约
# ---------------------------------------------------------------------------

class TestGeminiProvider:
    """Gemini Provider 契约."""

    def test_gemini_parses_candidates_parts_text(self):
        """Gemini 必须解析 candidates[0].content.parts[0].text."""
        from src.utils.llm_provider import GeminiProvider

        provider = GeminiProvider(
            api_key="fake-gemini-key",
            model="gemini-test-model",
        )

        with patch("httpx.post", return_value=_fake_gemini_response("Gemini 输出")):
            result = provider.chat("翻译以下内容")

        assert result.text == "Gemini 输出"
        assert result.provider == "gemini"
        assert result.model == "gemini-test-model"
        assert result.cached is False

    def test_gemini_empty_content_raises_empty_response_error(self):
        """Gemini 返回空 content 时应抛出 EmptyResponseError."""
        from src.utils.llm_provider import GeminiProvider, EmptyResponseError

        provider = GeminiProvider(
            api_key="fake-key",
            model="m",
        )

        with patch("httpx.post", return_value=_fake_gemini_response("")):
            with pytest.raises(EmptyResponseError):
                provider.chat("prompt")

    def test_gemini_429_raises_rate_limit_error(self):
        """Gemini HTTP 429 应抛出 RateLimitError."""
        from src.utils.llm_provider import GeminiProvider, RateLimitError

        provider = GeminiProvider(
            api_key="fake-key",
            model="m",
        )

        with patch("httpx.post", return_value=_fake_gemini_response("", status_code=429)):
            with pytest.raises(RateLimitError):
                provider.chat("prompt")

    def test_gemini_500_raises_provider_error(self):
        """Gemini HTTP 500 应抛出 ProviderError."""
        from src.utils.llm_provider import GeminiProvider, ProviderError

        provider = GeminiProvider(
            api_key="fake-key",
            model="m",
        )

        with patch("httpx.post", return_value=_fake_gemini_response("", status_code=500)):
            with pytest.raises(ProviderError):
                provider.chat("prompt")


# ---------------------------------------------------------------------------
# LLM Router 契约 (Agnes 优先, Gemini fallback)
# ---------------------------------------------------------------------------

class TestLLMRouter:
    """Router 必须 Agnes 优先, 429 时 fallback 到 Gemini."""

    def test_router_prefers_agnes(self):
        """正常情况下 Router 使用 Agnes, 不调用 Gemini."""
        from src.utils.llm_provider import LLMRouter

        router = LLMRouter(
            agnes_base_url="https://agnes.example.com/v1",
            agnes_api_key="fake-agnes",
            agnes_model="agnes-m",
            gemini_api_key="fake-gemini",
            gemini_model="gemini-m",
        )

        agnes_called = False
        gemini_called = False

        def fake_post(url, **kwargs):
            nonlocal agnes_called, gemini_called
            if "agnes" in url:
                agnes_called = True
                return _fake_agnes_response("from agnes")
            elif "googleapis" in url or "gemini" in url:
                gemini_called = True
                return _fake_gemini_response("from gemini")
            return _fake_agnes_response("default")

        with patch("httpx.post", side_effect=fake_post):
            result = router.chat("hello")

        assert result.text == "from agnes"
        assert result.provider == "agnes"
        assert result.model == "agnes-m"
        assert agnes_called is True
        assert gemini_called is False

    def test_router_falls_back_to_gemini_on_429(self):
        """Agnes 返回 429 时, Router 必须 fallback 到 Gemini."""
        from src.utils.llm_provider import LLMRouter

        router = LLMRouter(
            agnes_base_url="https://agnes.example.com/v1",
            agnes_api_key="fake-agnes",
            agnes_model="agnes-m",
            gemini_api_key="fake-gemini",
            gemini_model="gemini-m",
        )

        def fake_post(url, **kwargs):
            if "agnes" in url:
                return _fake_agnes_response("", status_code=429)
            return _fake_gemini_response("gemini fallback ok")

        with patch("httpx.post", side_effect=fake_post):
            result = router.chat("hello")

        assert result.text == "gemini fallback ok"
        assert result.provider == "gemini"
        assert result.model == "gemini-m"

    def test_both_providers_fail_raises_all_providers_failed(self):
        """双 Provider 全部失败时, Router 必须抛出 AllProvidersFailed."""
        from src.utils.llm_provider import LLMRouter, AllProvidersFailed, LLMProviderError

        router = LLMRouter(
            agnes_base_url="https://agnes.example.com/v1",
            agnes_api_key="fake-agnes",
            agnes_model="agnes-m",
            gemini_api_key="fake-gemini",
            gemini_model="gemini-m",
        )

        def fake_post(url, **kwargs):
            if "agnes" in url:
                return _fake_agnes_response("", status_code=429)
            return _fake_gemini_response("", status_code=500)

        with patch("httpx.post", side_effect=fake_post):
            with pytest.raises(AllProvidersFailed):
                router.chat("hello")

    def test_router_both_429_raises_all_providers_failed(self):
        from src.utils.llm_provider import AllProvidersFailed, LLMRouter
        router=LLMRouter("https://agnes.example.com/v1","a","am","g","gm")
        def fake_post(url, **kwargs):
            return _fake_agnes_response("",429) if "agnes" in url else _fake_gemini_response("",429)
        with patch("httpx.post",side_effect=fake_post):
            with pytest.raises(AllProvidersFailed):
                router.chat("hello")

    def test_all_providers_failed_inherits_llm_provider_error(self):
        """AllProvidersFailed 必须继承 LLMProviderError."""
        from src.utils.llm_provider import AllProvidersFailed, LLMProviderError

        assert issubclass(AllProvidersFailed, LLMProviderError)


# ---------------------------------------------------------------------------
# LLMResult dataclass 契约
# ---------------------------------------------------------------------------

class TestLLMResult:
    """LLMResult dataclass 基本契约."""

    def test_llmresult_fields(self):
        from src.utils.llm_provider import LLMResult

        r = LLMResult(text="hello", provider="agnes", model="m1")
        assert r.text == "hello"
        assert r.provider == "agnes"
        assert r.model == "m1"
        assert r.cached is False
        assert r.finish_reason is None

    def test_llmresult_optional_fields(self):
        from src.utils.llm_provider import LLMResult

        r = LLMResult(text="t", provider="p", model="m", cached=True, finish_reason="stop")
        assert r.cached is True
        assert r.finish_reason == "stop"




def test_translator_public_functions_use_agnes_result(monkeypatch):
    from src.utils import gemini_translator as t
    from src.utils.llm_provider import LLMResult
    class R:
        prompts=[]
        def __init__(self, **kwargs): pass
        def chat(self, prompt):
            self.prompts.append(prompt)
            return LLMResult(text="Agnes fake result", provider="agnes", model="m")
    monkeypatch.setattr(t, "AGNES_API_KEY", "a", raising=False)
    monkeypatch.setattr(t, "GEMINI_API_KEY", None)
    monkeypatch.setattr(t, "LLMRouter", R, raising=False)
    assert t.translate_to_chinese("A sufficiently long abstract.") == "Agnes fake result"
    assert t.generate_brief("A sufficiently long article content here.") == "Agnes fake result"
    assert t.summarize_blog_article("A" * 60) == "Agnes fake result"
    assert t.generate_news_brief("News title", "A" * 30) == "Agnes fake result"
    assert t.expand_product_tagline("Product", "Useful tagline") == "Agnes fake result"
    assert len(R.prompts) == 5


def test_translator_uses_gemini_fallback_result(monkeypatch):
    from src.utils import gemini_translator as t
    from src.utils.llm_provider import LLMResult
    class R:
        def __init__(self, **kwargs): pass
        def chat(self, prompt): return LLMResult("Gemini fallback", "gemini", "gm")
    monkeypatch.setattr(t, "AGNES_API_KEY", "a", raising=False)
    monkeypatch.setattr(t, "GEMINI_API_KEY", "g")
    monkeypatch.setattr(t, "LLMRouter", R, raising=False)
    monkeypatch.setattr(t.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden")))
    assert t.generate_brief("A sufficiently long article content for fallback.") == "Gemini fallback"


def test_translator_makes_no_network_call_without_provider_key(monkeypatch):
    from src.utils import gemini_translator as t
    def fail(**kwargs): raise AssertionError("router must not be constructed")
    monkeypatch.setattr(t, "AGNES_API_KEY", None, raising=False)
    monkeypatch.setattr(t, "GEMINI_API_KEY", None)
    monkeypatch.setattr(t, "LLMRouter", fail, raising=False)
    assert t.translate_to_chinese("A" * 120, 10) == "A" * 10 + "..."


def test_news_brief_junk_falls_back_to_title_inference_once(monkeypatch):
    from src.utils import gemini_translator as t
    from src.utils.llm_provider import LLMResult
    class R:
        calls=[]
        def __init__(self, **kwargs): pass
        def chat(self, prompt):
            self.calls.append(prompt)
            text="[JUNK]" if "垃圾熔断" in prompt else "标题推断摘要"
            return LLMResult(text, "agnes", "am")
    monkeypatch.setattr(t, "AGNES_API_KEY", "a", raising=False)
    monkeypatch.setattr(t, "GEMINI_API_KEY", None)
    monkeypatch.setattr(t, "LLMRouter", R, raising=False)
    assert t.generate_news_brief("News title", "A" * 30) == "标题推断摘要"
    assert len(R.calls) == 2
# TASK4_TESTS

def test_agnes_budget_acquire_allows_three_calls_then_denies():
    from src.utils.llm_provider import AgnesBudget

    budget = AgnesBudget(max_calls=3, min_interval=0)

    assert [budget.acquire() for _ in range(4)] == [True, True, True, False]
    assert budget.remaining == 0


def test_cache_key_contains_provider_model_task_prompt_version_and_content_hash():
    from src.utils.llm_provider import cache_key

    key = cache_key(provider="agnes", model="agnes-m", task="news_brief", prompt_version="v1", content="same source content")

    assert "agnes" in key
    assert "agnes-m" in key
    assert "news_brief" in key
    assert "v1" in key
    assert "same source content" not in key


def test_l1_cache_hits_unchanged_content_and_misses_provider_or_prompt_variants():
    from src.utils.llm_provider import LLMCache, LLMResult, cache_key

    cache = LLMCache()
    result = LLMResult(text="缓存结果", provider="agnes", model="agnes-m")
    key = cache_key("agnes", "agnes-m", "news_brief", "v1", "same")
    cache.put(key, result)

    cached = cache.get(key)
    assert cached is not None
    assert cached.text == "缓存结果"
    assert cached.cached is True
    assert cache.get(cache_key("gemini", "gemini-m", "news_brief", "v1", "same")) is None
    assert cache.get(cache_key("agnes", "agnes-m", "news_brief", "v2", "same")) is None


def test_router_cache_hit_does_not_call_provider_again():
    from src.utils.llm_provider import LLMCache, LLMResult, LLMRouter

    router = LLMRouter(
        agnes_base_url="https://agnes.example.com/v1",
        agnes_api_key="fake-agnes",
        agnes_model="agnes-m",
        gemini_api_key="fake-gemini",
        gemini_model="gemini-m",
        cache=LLMCache(), task="news_brief", prompt_version="v1",
    )
    router.agnes.chat = MagicMock(return_value=LLMResult("first", "agnes", "agnes-m"))
    router.gemini.chat = MagicMock()

    first = router.chat("same prompt")
    second = router.chat("same prompt")

    assert first.cached is False
    assert second.cached is True
    assert second.text == "first"
    router.agnes.chat.assert_called_once_with("same prompt")
    router.gemini.chat.assert_not_called()


def test_budgeted_news_brief_gemini_fallback_consumes_no_extra_agnes_call(monkeypatch):
    from src.utils import gemini_translator as translator
    from src.utils.llm_provider import AgnesBudget, LLMResult

    class Router:
        class Agnes:
            api_key = "fake-agnes"

        agnes = Agnes()
        class Gemini:
            max_tokens = None
            temperature = None
        gemini = Gemini()

        def get_cached(self, prompt):
            return None

        def chat(self, prompt):
            return LLMResult("Gemini fallback", "gemini", "gemini-m")

    budget = AgnesBudget(max_calls=3, min_interval=0)
    monkeypatch.setattr(translator, "AGNES_API_KEY", "fake-agnes", raising=False)
    monkeypatch.setattr(translator, "GEMINI_API_KEY", "fake-gemini", raising=False)

    result = translator.generate_news_brief("News title", "A sufficiently long source content for fallback.", _router=Router(), _budget=budget)

    assert result == "Gemini fallback"
    assert budget.remaining == 2


# TASK3_TESTS
if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_summarize_blog_article_passes_shared_context(monkeypatch):
    from src.utils import gemini_translator as t
    from src.utils.llm_provider import LLMResult

    class P:
        api_key = 'shared'
        max_tokens = None
        temperature = None

    class R:
        def __init__(self):
            self.agnes = P()
            self.calls = []
        def get_cached(self, prompt):
            self.calls.append(('cache', prompt))
            return None
        def chat(self, prompt):
            self.calls.append(('chat', prompt))
            return LLMResult('ok', 'agnes', 'm')

    class B:
        def __init__(self):
            self.calls = 0
        def acquire(self):
            self.calls += 1
            return True

    router = R()
    budget = B()
    monkeypatch.setattr(t, 'AGNES_API_KEY', 'a', raising=False)
    monkeypatch.setattr(t, 'GEMINI_API_KEY', None, raising=False)
    monkeypatch.setattr(t, 'LLMRouter', lambda **k: (_ for _ in ()).throw(
        AssertionError('new router')), raising=False)

    result = t.summarize_blog_article(
        'A real blog article body with enough content to enter chat. ' * 2,
        _router=router, _budget=budget)

    assert result == 'ok'
    assert budget.calls == 1
    assert [kind for kind, _ in router.calls] == ['cache', 'chat']
    assert (router.agnes.max_tokens, router.agnes.temperature) == (256, 0.4)
