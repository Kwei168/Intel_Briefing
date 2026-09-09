"""
LLM Provider — unified multi-provider LLM abstraction.

Provides:
- AgnesProvider:  OpenAI-compatible (Agnes) chat provider
- GeminiProvider: Google Gemini chat provider
- LLMRouter:      Agnes-first with Gemini fallback on 429

Error hierarchy:
- LLMProviderError        (base)
  - ProviderError         (generic provider failure — non-429 HTTP, parse, network)
  - RateLimitError        (HTTP 429)
  - EmptyResponseError    (provider returned empty content)
  - AllProvidersFailed    (router exhausted all providers)

Usage:
    from src.utils.llm_provider import LLMRouter, LLMProviderError

    router = LLMRouter(agnes_base_url=..., agnes_api_key=..., ...)
    try:
        result = router.chat("translate ...")
        print(result.text, result.provider, result.model)
    except LLMProviderError as exc:
        logger.error("LLM call failed: %s", exc)
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class LLMProviderError(Exception):
    """Base error for all LLM provider failures.

    Raised for:
    - HTTP errors from providers
    - Empty / unparseable responses
    - All providers exhausted in router
    """


class ProviderError(LLMProviderError):
    """Generic provider-level error (non-rate-limit HTTP or parse failures)."""


class RateLimitError(LLMProviderError):
    """Provider returned HTTP 429 — rate limit exceeded."""


class EmptyResponseError(LLMProviderError):
    """Provider returned a successful response but with empty content."""


class AllProvidersFailed(LLMProviderError):
    """Router tried every provider and all of them failed."""


# ---------------------------------------------------------------------------
# LLMResult — uniform return type
# ---------------------------------------------------------------------------

@dataclass
class LLMResult:
    """Uniform result returned by every provider and the router."""

    text: str
    provider: str
    model: str
    cached: bool = False
    finish_reason: Optional[str] = None


def cache_key(provider: str, model: str, task: str, prompt_version: str, content: str) -> str:
    """Build a stable L1 cache key without storing source content in the key."""
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return "|".join((provider, model, task, prompt_version, content_hash))


class LLMCache:
    """Small process-local LRU cache for completed LLM results."""

    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[str, LLMResult] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[LLMResult]:
        with self._lock:
            result = self._entries.pop(key, None)
            if result is None:
                return None
            self._entries[key] = result
        return LLMResult(
            text=result.text,
            provider=result.provider,
            model=result.model,
            cached=True,
            finish_reason=result.finish_reason,
        )

    def put(self, key: str, result: LLMResult) -> None:
        stored = LLMResult(
            text=result.text,
            provider=result.provider,
            model=result.model,
            cached=False,
            finish_reason=result.finish_reason,
        )
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = stored
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class AgnesBudget:
    """Process-local Agnes call budget and monotonic pacing gate."""

    def __init__(
        self,
        max_calls: Optional[int] = None,
        min_interval: Optional[float] = None,
        *,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if max_calls is None or min_interval is None:
            from src.config import AGNES_MAX_CALLS_PER_RUN, AGNES_MIN_INTERVAL
            if max_calls is None:
                max_calls = AGNES_MAX_CALLS_PER_RUN
            if min_interval is None:
                min_interval = AGNES_MIN_INTERVAL
        self.remaining = max(0, int(max_calls))
        self.min_interval = max(0.0, float(min_interval))
        self.next_at = 0.0
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()

    def available(self) -> bool:
        with self._lock:
            return self.remaining > 0 and self._clock() >= self.next_at

    def acquire(self) -> bool:
        """Reserve one real Agnes request when budget and pacing permit it."""
        with self._lock:
            now = self._clock()
            if self.remaining <= 0 or now < self.next_at:
                return False
            self.remaining -= 1
            self.next_at = now + self.min_interval
            return True


# ---------------------------------------------------------------------------
# AgnesProvider — OpenAI-compatible
# ---------------------------------------------------------------------------

_DEFAULT_AGNES_MAX_TOKENS = 4096
_DEFAULT_AGNES_TEMPERATURE = 0.7


class AgnesProvider:
    """OpenAI-compatible chat provider for the Agnes endpoint.

    Sends ``POST {base_url}/chat/completions`` with the standard
    ``model / messages / max_tokens / temperature`` payload plus
    ``chat_template_kwargs.enable_thinking = False``.

    Parameters
    ----------
    base_url:
        Base URL *without* trailing slash, e.g.
        ``https://agnes.example.com/v1``.
    api_key:
        Bearer token for the Authorization header.
    model:
        Model identifier sent in the payload.
    max_tokens / temperature:
        Optional overrides for generation parameters.
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        max_tokens: int = _DEFAULT_AGNES_MAX_TOKENS,
        temperature: float = _DEFAULT_AGNES_TEMPERATURE,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = _normalize_agnes_url(base_url)
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, prompt: str) -> LLMResult:
        """Send *prompt* to Agnes and return an :class:`LLMResult`.

        Raises
        ------
        RateLimitError
            On HTTP 429.
        ProviderError
            On other HTTP errors or parse failures.
        EmptyResponseError
            When the response content is empty.
        """
        if not self.api_key:
            raise ProviderError("Agnes API key not configured")

        url = self.base_url
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "chat_template_kwargs": {"enable_thinking": False},
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Agnes request failed: {exc}") from exc

        # --- HTTP-level error handling ---
        if response.status_code == 429:
            raise RateLimitError(
                f"Agnes rate limit (HTTP 429). "
                f"Response: {_safe_truncate(response)}"
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Agnes HTTP {response.status_code}. "
                f"Response: {_safe_truncate(response)}"
            )

        # --- Parse OpenAI-compatible response ---
        try:
            data = response.json()
            content: str = data["choices"][0]["message"]["content"]
            finish_reason = data["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"Agnes response parse error: {exc}") from exc

        if not content:
            raise EmptyResponseError("Agnes returned empty content")

        return LLMResult(
            text=content,
            provider="agnes",
            model=self.model,
            cached=False,
            finish_reason=finish_reason,
        )


# ---------------------------------------------------------------------------
# GeminiProvider
# ---------------------------------------------------------------------------

_DEFAULT_GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
)
_DEFAULT_GEMINI_MAX_TOKENS = 4096
_DEFAULT_GEMINI_TEMPERATURE = 0.7
_DEFAULT_GEMINI_TIMEOUT = 60.0


class GeminiProvider:
    """Google Gemini chat provider via the REST ``generateContent`` API.

    Sends ``POST {api_url}/{model}:generateContent?key={api_key}`` with
    ``contents`` and ``generationConfig``.

    Parameters
    ----------
    api_key:
        Google AI Studio / Vertex API key.
    model:
        Model identifier, e.g. ``gemini-2.0-flash``.
    api_url:
        Base models URL (without trailing slash).
    max_tokens / temperature:
        Optional overrides for generation parameters.
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        api_url: str = _DEFAULT_GEMINI_API_URL,
        max_tokens: int = _DEFAULT_GEMINI_MAX_TOKENS,
        temperature: float = _DEFAULT_GEMINI_TEMPERATURE,
        timeout: float = _DEFAULT_GEMINI_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.api_url = api_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, prompt: str) -> LLMResult:
        """Send *prompt* to Gemini and return an :class:`LLMResult`.

        Raises
        ------
        RateLimitError
            On HTTP 429.
        ProviderError
            On other HTTP errors or parse failures.
        EmptyResponseError
            When the response content is empty.
        """
        if not self.api_key:
            raise ProviderError("Gemini API key not configured")

        url = f"{self.api_url}/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": self.max_tokens,
                "temperature": self.temperature,
            },
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Gemini request failed: {exc}") from exc

        if response.status_code == 429:
            raise RateLimitError(
                f"Gemini rate limit (HTTP 429). "
                f"Response: {_safe_truncate(response)}"
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Gemini HTTP {response.status_code}. "
                f"Response: {_safe_truncate(response)}"
            )

        # --- Parse Gemini response ---
        try:
            data = response.json()
            text: str = data["candidates"][0]["content"]["parts"][0]["text"]
            finish_reason = data["candidates"][0].get("finishReason")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"Gemini response parse error: {exc}") from exc

        if not text:
            raise EmptyResponseError("Gemini returned empty content")

        return LLMResult(
            text=text,
            provider="gemini",
            model=self.model,
            cached=False,
            finish_reason=finish_reason,
        )


# ---------------------------------------------------------------------------
# LLMRouter — Agnes-first with Gemini fallback
# ---------------------------------------------------------------------------

class LLMRouter:
    """Route chat requests: Agnes first, fall back to Gemini on 429.

    Parameters
    ----------
    agnes_base_url, agnes_api_key, agnes_model:
        Forwarded to :class:`AgnesProvider`.
    gemini_api_key, gemini_model:
        Forwarded to :class:`GeminiProvider`.
    gemini_api_url:
        Optional override for the Gemini models base URL.
    """

    def __init__(
        self,
        agnes_base_url: str,
        agnes_api_key: str,
        agnes_model: str,
        gemini_api_key: str,
        gemini_model: str,
        *,
        gemini_api_url: str = _DEFAULT_GEMINI_API_URL,
        agnes_budget: Optional[AgnesBudget] = None,
        cache: Optional[LLMCache] = None,
        task: str = "chat",
        prompt_version: str = "v1",
    ) -> None:
        self.agnes_budget = agnes_budget
        self.cache = cache
        self.task = task
        self.prompt_version = prompt_version
        self.last_result: Optional[LLMResult] = None
        self.agnes = AgnesProvider(
            base_url=agnes_base_url,
            api_key=agnes_api_key,
            model=agnes_model,
        )
        self.gemini = GeminiProvider(
            api_key=gemini_api_key,
            model=gemini_model,
            api_url=gemini_api_url,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cached(self, prompt: str) -> Optional[LLMResult]:
        """Return a cached result for either configured provider, if present."""
        if self.cache is None:
            return None
        for provider, model in (
            ("agnes", self.agnes.model),
            ("gemini", self.gemini.model),
        ):
            result = self.cache.get(cache_key(provider, model, self.task, self.prompt_version, prompt))
            if result is not None:
                self.last_result = result
                return result
        return None

    def _store_cached(self, prompt: str, result: LLMResult) -> None:
        if self.cache is not None:
            self.cache.put(
                cache_key(result.provider, result.model, self.task, self.prompt_version, prompt),
                result,
            )

    def chat(self, prompt: str) -> LLMResult:
        """Try Agnes; on 429 fall back to Gemini.

        Raises
        ------
        AllProvidersFailed
            If both providers fail for any reason, including both returning 429.
        """
        cached = self.get_cached(prompt)
        if cached is not None:
            return cached

        errors: list[Exception] = []

        # --- Primary: Agnes ---
        try:
            if self.agnes_budget is not None and self.agnes.api_key and not self.agnes_budget.acquire():
                raise ProviderError("Agnes budget exhausted")
            result = self.agnes.chat(prompt)
            self.last_result = result
            self._store_cached(prompt, result)
            return result
        except RateLimitError as exc:
            logger.warning("Agnes rate-limited, falling back to Gemini: %s", exc)
            errors.append(exc)
        except LLMProviderError as exc:
            # Non-rate-limit Agnes failure — still try Gemini as courtesy
            logger.warning("Agnes failed (%s), falling back to Gemini", exc)
            errors.append(exc)

        # --- Fallback: Gemini ---
        try:
            result = self.gemini.chat(prompt)
            self.last_result = result
            self._store_cached(prompt, result)
            return result
        except LLMProviderError as exc:
            errors.append(exc)

        raise AllProvidersFailed(
            f"All providers failed: {[str(e) for e in errors]}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_agnes_url(base_url: str) -> str:
    """Normalize an Agnes base URL or complete chat endpoint."""
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _safe_truncate(response: httpx.Response, max_len: int = 200) -> str:
    """Return a truncated text snippet from *response* for error messages.

    Never logs the full body to avoid leaking secrets.
    """
    try:
        text = response.text
    except Exception:
        return "<unreadable>"
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
