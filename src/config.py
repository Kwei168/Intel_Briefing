"""
Intel Briefing - Unified Configuration Layer

Single source of truth for all configuration values.
Replaces the fragmented pattern of manual .env parsing, load_dotenv(),
and os.getenv() scattered across sensors.

Usage:
    from config import cfg

    # Access any config value
    api_key = cfg.xai_api_key
    model = cfg.xai_model
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

# Load .env from project root (handles both local dev and CI)
# Walk up from this file (src/config.py) to find .env at project root
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_project_root, ".env"))


@dataclass(frozen=True)
class IntelConfig:
    """Immutable configuration for the Intel Briefing engine.

    Resolution order for each value:
    1. Environment variable (set by CI/CD or .env)
    2. Hardcoded default (safe fallback)

    All secrets come from env vars. Non-secret operational params
    have sensible defaults.
    """

    # === Core API Keys (SECRETS — no defaults) ===
    gemini_api_key: Optional[str] = field(default=None)
    xai_api_key: Optional[str] = field(default=None)
    github_token: Optional[str] = field(default=None)
    producthunt_token: Optional[str] = field(default=None)
    agnes_api_key: Optional[str] = field(default=None)

    # === XAI / Grok Configuration ===
    # Aligned with .github/workflows/daily-report.yml actual values
    xai_base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    xai_model: str = "x-ai/grok-4-fast"

    # === Gemini Configuration ===
    gemini_api_url: str = "https://generativelanguage.googleapis.com/v1beta/models"
    gemini_model: str = "gemini-2.0-flash"
    gemini_timeout: int = 60
    gemini_max_retries: int = 3

    # === Agnes (OpenAI-compatible) Configuration ===
    agnes_api_url: str = "https://apihub.agnes-ai.com/v1/chat/completions"
    agnes_model: str = "agnes-2.5-flash"
    agnes_timeout: int = 30
    agnes_concurrency: int = 1
    agnes_min_interval: float = 45.0
    agnes_max_calls_per_run: int = 3
    agnes_max_retries: int = 1

    # === LLM Provider Routing ===
    llm_provider: str = "agnes"
    llm_fallback_provider: str = "gemini"

    # === Jina Reader Configuration ===
    jina_reader_url: str = "https://r.jina.ai/"
    jina_timeout: int = 30
    jina_max_chars: int = 15000

    # === Operational Parameters ===
    fetch_timeout: int = 15
    grok_timeout: int = 120
    limit_per_source: int = 10
    max_hn_blogs: int = 5
    content_truncate_limit: int = 3000
    gemini_rate_limit_delay: float = 1.5

    # === StarHub Bridge ===
    starhub_snapshot_url: str = "https://kwei168.github.io/starhub/rss_api_snapshot.json"
    starhub_bridge_enabled: bool = True

    # === Feature Flags ===
    enable_grok_sentiment: bool = True
    enable_link_verification: bool = True

    @classmethod
    def from_env(cls) -> "IntelConfig":
        """Build config from environment variables."""
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            xai_api_key=os.getenv("XAI_API_KEY"),
            github_token=os.getenv("GITHUB_TOKEN"),
            producthunt_token=os.getenv("PRODUCTHUNT_TOKEN"),
            agnes_api_key=os.getenv("AGNES_API_KEY"),
            xai_base_url=os.getenv(
                "XAI_BASE_URL",
                "https://openrouter.ai/api/v1/chat/completions",
            ),
            xai_model=os.getenv("XAI_MODEL", "x-ai/grok-4-fast"),
            gemini_api_url=os.getenv(
                "GEMINI_API_URL",
                "https://generativelanguage.googleapis.com/v1beta/models",
            ),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            gemini_timeout=int(os.getenv("GEMINI_TIMEOUT", "60")),
            gemini_max_retries=int(os.getenv("GEMINI_MAX_RETRIES", "3")),
            agnes_api_url=os.getenv("AGNES_API_URL", "https://apihub.agnes-ai.com/v1/chat/completions"),
            agnes_model=os.getenv("AGNES_MODEL", "agnes-2.5-flash"),
            agnes_timeout=int(os.getenv("AGNES_TIMEOUT", "30")),
            agnes_concurrency=max(1, int(os.getenv("AGNES_CONCURRENCY", "1"))),
            agnes_min_interval=float(max(1, int(os.getenv("AGNES_MIN_INTERVAL", "45")))),
            agnes_max_calls_per_run=max(1, int(os.getenv("AGNES_MAX_CALLS_PER_RUN", "3"))),
            agnes_max_retries=max(1, int(os.getenv("AGNES_MAX_RETRIES", "1"))),
            llm_provider=(os.getenv("LLM_PROVIDER", "agnes")).lower(),
            llm_fallback_provider=(os.getenv("LLM_FALLBACK_PROVIDER", "gemini")).lower(),
            jina_reader_url=os.getenv("JINA_READER_URL", "https://r.jina.ai/"),
            jina_timeout=int(os.getenv("JINA_TIMEOUT", "30")),
            jina_max_chars=int(os.getenv("JINA_MAX_CHARS", "15000")),
            fetch_timeout=int(os.getenv("FETCH_TIMEOUT", "15")),
            grok_timeout=int(os.getenv("GROK_TIMEOUT", "120")),
            limit_per_source=int(os.getenv("LIMIT_PER_SOURCE", "10")),
            max_hn_blogs=int(os.getenv("MAX_HN_BLOGS", "5")),
            content_truncate_limit=int(os.getenv("CONTENT_TRUNCATE_LIMIT", "3000")),
            enable_grok_sentiment=os.getenv("ENABLE_GROK_SENTIMENT", "true").lower() == "true",
            enable_link_verification=os.getenv("ENABLE_LINK_VERIFICATION", "true").lower() == "true",
            starhub_snapshot_url=os.getenv(
                "STARHUB_SNAPSHOT_URL",
                "https://kwei168.github.io/starhub/rss_api_snapshot.json",
            ),
            starhub_bridge_enabled=os.getenv("STARHUB_BRIDGE_ENABLED", "true").lower() == "true",
        )

    def validate(self) -> list[str]:
        """Return a list of warnings for missing critical config."""
        warnings = []
        if not self.xai_api_key:
            warnings.append("XAI_API_KEY not set — Grok sensor will be disabled")
        if not self.github_token:
            warnings.append("GITHUB_TOKEN not set — GitHub Trending will be disabled")

        # --- LLM provider key validation (provider-aware) ---
        def _has_key(provider: str) -> bool:
            if provider == "agnes":
                return bool(self.agnes_api_key)
            if provider == "gemini":
                return bool(self.gemini_api_key)
            return False

        primary = self.llm_provider
        fallback = self.llm_fallback_provider
        primary_ok = _has_key(primary)
        fallback_ok = _has_key(fallback)

        if not primary_ok and not fallback_ok:
            warnings.append(
                f"No LLM provider key configured "
                f"(primary={primary}, fallback={fallback}) — "
                f"falling back to RSS summaries only"
            )
        elif not primary_ok:
            warnings.append(
                f"{primary.upper()}_API_KEY not set — "
                f"{primary.capitalize()} LLM provider disabled, "
                f"falling back to {fallback.capitalize()}"
            )
        # If primary key is present, no LLM warning regardless of fallback status

        return warnings


# Singleton instance — import this everywhere
cfg = IntelConfig.from_env()

# Backward-compatible module-level exports
# (used by gemini_translator.py, jina_reader.py, report_generator.py)
GEMINI_RATE_LIMIT_DELAY = cfg.gemini_rate_limit_delay
GEMINI_API_KEY = cfg.gemini_api_key
GEMINI_API_URL = cfg.gemini_api_url
GEMINI_MODEL = cfg.gemini_model
GEMINI_TIMEOUT = cfg.gemini_timeout
GEMINI_MAX_RETRIES = cfg.gemini_max_retries
JINA_READER_URL = cfg.jina_reader_url
JINA_TIMEOUT = cfg.jina_timeout
JINA_MAX_CHARS = cfg.jina_max_chars
CONTENT_TRUNCATE_LIMIT = cfg.content_truncate_limit
STARHUB_SNAPSHOT_URL = cfg.starhub_snapshot_url
STARHUB_BRIDGE_ENABLED = cfg.starhub_bridge_enabled

# Agnes LLM provider exports
AGNES_API_KEY = cfg.agnes_api_key
AGNES_API_URL = cfg.agnes_api_url
AGNES_MODEL = cfg.agnes_model
AGNES_TIMEOUT = cfg.agnes_timeout
AGNES_CONCURRENCY = cfg.agnes_concurrency
AGNES_MIN_INTERVAL = cfg.agnes_min_interval
AGNES_MAX_CALLS_PER_RUN = cfg.agnes_max_calls_per_run
AGNES_MAX_RETRIES = cfg.agnes_max_retries

# LLM routing exports
LLM_PROVIDER = cfg.llm_provider
LLM_FALLBACK_PROVIDER = cfg.llm_fallback_provider
