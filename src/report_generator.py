#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Report Generator - 报告生成模块
负责将情报数据转换为 Markdown 报告
"""

import time
import logging
from collections import Counter, OrderedDict
from datetime import datetime

logger = logging.getLogger(__name__)

from src.config import (
    GEMINI_RATE_LIMIT_DELAY, AGNES_API_KEY, GEMINI_API_KEY,
    AGNES_API_URL, AGNES_MODEL, GEMINI_API_URL, GEMINI_MODEL,
)
from src.utils.llm_provider import AgnesBudget, LLMCache, LLMRouter, cache_key

# --- Gemini Translator ---
try:
    from src.utils.gemini_translator import translate_to_chinese, summarize_blog_article, generate_brief, generate_news_brief, expand_product_tagline
    GEMINI_AVAILABLE = True
    LLM_AVAILABLE = bool(AGNES_API_KEY or GEMINI_API_KEY)
except ImportError:
    GEMINI_AVAILABLE = False
    LLM_AVAILABLE = False

# --- Jina Reader (Full Content Fetcher) ---
try:
    from src.utils.jina_reader import fetch_full_content
    JINA_AVAILABLE = True
except ImportError:
    JINA_AVAILABLE = False
    logger.info("Jina Reader not available, using RSS description only.")

if not GEMINI_AVAILABLE:
    logger.info("Gemini translator not available, using English summaries.")
    def translate_to_chinese(text, max_chars=100, _router=None, _budget=None):
        return text[:max_chars] + "..." if len(text) > max_chars else text

    def summarize_blog_article(content, mode="brief", _router=None, _budget=None):
        return ""

    def generate_brief(content, category="general", _router=None, _budget=None):
        return ""

    def generate_news_brief(title, content="", category="tech", _depth=0, _router=None, _budget=None):
        return ""

    def expand_product_tagline(name, tagline, _router=None, _budget=None):
        return ""


BRIEF_TASK = "news_brief"
BRIEF_PROMPT_VERSION = "v1"
_BRIEF_CACHE = LLMCache()
_BRIEF_BUDGET = AgnesBudget()
_BRIEF_ROUTER = LLMRouter(
    agnes_base_url=AGNES_API_URL,
    agnes_api_key=AGNES_API_KEY or "",
    agnes_model=AGNES_MODEL,
    gemini_api_key=GEMINI_API_KEY or "",
    gemini_model=GEMINI_MODEL,
    gemini_api_url=GEMINI_API_URL,
    cache=_BRIEF_CACHE,
    task=BRIEF_TASK,
    prompt_version=BRIEF_PROMPT_VERSION,
)

def _select_diverse_items(items, limit, max_per_source=2):
    """按来源轮询选取条目，避免单一信源占满一个栏目。"""
    groups = OrderedDict()
    seen_titles = set()
    seen_urls = set()
    for item in items or []:
        title = " ".join(str(item.get("title", "")).split()).casefold()
        url = str(item.get("url", "")).strip()
        if not title or (title in seen_titles) or (url and url in seen_urls):
            continue
        seen_titles.add(title)
        if url:
            seen_urls.add(url)
        source = str(item.get("category") or item.get("source") or "Unknown")
        groups.setdefault(source, []).append(item)
    selected = []
    source_counts = {}
    while len(selected) < limit and groups:
        progressed = False
        for source in list(groups):
            queue = groups[source]
            if queue and source_counts.get(source, 0) < max_per_source:
                selected.append(queue.pop(0))
                source_counts[source] = source_counts.get(source, 0) + 1
                progressed = True
                if len(selected) >= limit:
                    break
            if not queue or source_counts.get(source, 0) >= max_per_source:
                del groups[source]
        if not progressed:
            break
    return selected


def _signal_brief(item, category):
    """按预计算、中文复用、缓存、预算、LLM、RSS 的顺序生成短报。

    设置条目级字段:
    - _analysis_stage: precomputed | reused | agnes | gemini | rss_fallback | source_summary
    - _provider: agnes | gemini | None
    - _model: model string | None
    - _cached: bool
    - _failure_reason: budget_exhausted | llm_failed | no_content | llm_unavailable | None
    """
    if item.get("analysis_brief"):
        # Only set stage if not already set (avoid override on second call)
        if not item.get("_analysis_stage"):
            item["_analysis_stage"] = "precomputed"
        item.setdefault("_provider", None)
        item.setdefault("_model", None)
        item.setdefault("_cached", False)
        return item["analysis_brief"]

    for field in ("summary_cn", "translation"):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            value = value.strip()
            item["analysis_brief"] = value
            item["_analysis_stage"] = "reused"
            item["_provider"] = None
            item["_model"] = None
            item["_cached"] = False
            return value

    content = (item.get("content") or item.get("summary") or "").strip()
    rss_summary = (item.get("summary") or item.get("content") or "").strip()
    request_content = "\n".join((item.get("title", ""), category, content))
    failure_reason = None
    if item.get("starhub") and content and LLM_AVAILABLE:
        for provider, model in (("agnes", AGNES_MODEL), ("gemini", GEMINI_MODEL)):
            cached = _BRIEF_CACHE.get(cache_key(provider, model, BRIEF_TASK, BRIEF_PROMPT_VERSION, request_content))
            if cached is not None:
                item["analysis_brief"] = cached.text
                item["_analysis_stage"] = "reused"
                item["_provider"] = cached.provider
                item["_model"] = cached.model
                item["_cached"] = True
                return cached.text
        if not _BRIEF_BUDGET.available():
            brief = ""
            failure_reason = "budget_exhausted"
        else:
            brief = generate_news_brief(
                item.get("title", ""),
                content,
                category=category,
                _router=_BRIEF_ROUTER,
                _budget=_BRIEF_BUDGET,
            )
            if not brief:
                failure_reason = "llm_failed"
        if brief:
            latest = _BRIEF_ROUTER.last_result
            if latest is not None and latest.text == brief:
                _BRIEF_CACHE.put(
                    cache_key(latest.provider, latest.model, BRIEF_TASK, BRIEF_PROMPT_VERSION, request_content),
                    latest,
                )
            provider_name = latest.provider if latest else "agnes"
            item["analysis_brief"] = brief
            item["_analysis_stage"] = provider_name
            item["_provider"] = provider_name
            item["_model"] = latest.model if latest else None
            item["_cached"] = False
            return brief
    elif item.get("starhub"):
        if not content:
            failure_reason = "no_content"
        elif not LLM_AVAILABLE:
            failure_reason = "llm_unavailable"
    if item.get("starhub"):
        item["_analysis_stage"] = "rss_fallback"
        if failure_reason:
            item["_failure_reason"] = failure_reason
    else:
        item["_analysis_stage"] = "source_summary"
    fallback = rss_summary if item.get("starhub") else content
    return fallback[:240] if fallback else ""


def generate_report(intel: dict, date_str: str) -> str:
    """Generate magazine-style markdown report."""
    tech_items = _select_diverse_items(intel.get("tech_trends", []), 10)
    capital_items = _select_diverse_items(intel.get("capital_flow", []), 10)
    research_items = _select_diverse_items(intel.get("research", []), 5)
    product_items = _select_diverse_items(intel.get("product_gems", []), 8)
    community_items = _select_diverse_items(intel.get("community", []), 5)
    insights_items = _select_diverse_items(intel.get("insights", []), 5)
    selected_by_category = {
        "tech_trends": tech_items,
        "capital_flow": capital_items,
        "research": research_items,
        "product_gems": product_items,
        "community": community_items,
        "social": [],
        "insights": insights_items,
    }
    for category, selected in selected_by_category.items():
        for item in selected:
            if item.get("starhub"):
                _signal_brief(item, category)
    lines = [
        f"# 🌐 全球情报日报 (Global Intel Briefing)",
        f"**日期:** {date_str}",
        f"**生成时间:** {datetime.now().strftime('%H:%M')}",
        f"**数据源:** HN, GitHub, 36Kr, WallStreetCN, V2EX, PH, ArXiv, X, TechCrunch, MIT TR + StarHub (716 RSS)",
        "",
        "---",
        ""
    ]

    # --- Tech Trends ---
    lines.append("## 🛠️ 技术趋势 (Tech Trends)")
    lines.append("> Hacker News + GitHub Trending\n")

    if tech_items:
        for i, item in enumerate(tech_items, 1):
            title = item.get("title", "Untitled")
            url = item.get("url", "#")
            heat = item.get("heat", "")
            time_str = item.get("time", "")
            cat = item.get("category", "")

            lines.append(f"### {i}. [{title}]({url})")
            lines.append(f"📍 {cat} | 🔥 {heat} | 🕒 {time_str}")
            brief = _signal_brief(item, "tech")
            if brief:
                lines.append(f"> ⚡ {brief}")
            lines.append("")
    else:
        lines.append("*暂无数据*\n")

    # --- Capital Flow ---
    lines.append("## 💰 资本动向 (Capital Flow)")
    lines.append("> 36Kr + 华尔街见闻\n")

    if capital_items:
        for i, item in enumerate(capital_items, 1):
            title = item.get("title", "Untitled")
            url = item.get("url", "#")
            time_str = item.get("time", "")
            cat = item.get("category", "")

            lines.append(f"### {i}. [{title}]({url})")
            lines.append(f"📍 {cat} | 🕒 {time_str}")
            brief = _signal_brief(item, "capital")
            if brief:
                lines.append(f"> ⚡ {brief}")
            lines.append("")
    else:
        lines.append("*暂无数据*\n")

    # --- Research (ArXiv) ---
    lines.append("## 📚 学术前沿 (Research)")
    lines.append("> ArXiv AI/ML Papers\n")

    if research_items:
        for i, item in enumerate(research_items, 1):
            title = item.get("title", "Untitled")
            url = item.get("url", "#")
            authors = item.get("authors", "")
            time_str = item.get("time", "")
            summary = item.get("summary", "").replace("\n", " ")

            # Two-Tier Summary Logic
            # 1. Brief: 编辑风格摘要（80-120字，有主角有判断）
            brief_cn = generate_brief(summary, category="research", _router=_BRIEF_ROUTER, _budget=_BRIEF_BUDGET) if summary else ""
            
            # 添加延迟以避免 API 限速
            if LLM_AVAILABLE and summary:
                time.sleep(GEMINI_RATE_LIMIT_DELAY)
            
            # 2. Detail: 完整翻译（允许完整输出）
            detail_cn = translate_to_chinese(summary, max_chars=1200, _router=_BRIEF_ROUTER, _budget=_BRIEF_BUDGET) if summary else ""

            lines.append(f"### {i}. [{title}]({url})")
            if brief_cn:
                lines.append(f"> ⚡ {brief_cn}")

            lines.append(f"👤 {authors} | 📅 {time_str}")

            if detail_cn:
                lines.append("")
                lines.append(f"**详情:** {detail_cn}")

            lines.append("")
    else:
        lines.append("*暂无数据*\n")

    # --- Product Gems ---
    lines.append("## 💎 产品精选 (Product Gems)")
    lines.append("> Product Hunt Today\n")

    if product_items:
        for i, item in enumerate(product_items, 1):
            title = item.get("title", "Untitled")
            url = item.get("url", "#")
            heat = item.get("heat", "")
            tagline = item.get("tagline", "")
            grok_review = item.get("grok_review")
            topics = item.get("topics", [])

            # Anti-hallucination: Grok fallback URLs are guessed slugs, not real links
            is_grok_fallback = "grok-fallback" in topics
            if is_grok_fallback:
                from urllib.parse import quote
                search_url = f"https://www.google.com/search?q=site:producthunt.com+{quote(title)}"
                lines.append(f"### {i}. {title}")
                lines.append(f"> {tagline}")
                lines.append(f"⚠️ *链接未验证 (AI 推断)* | [🔍 搜索验证]({search_url})")
            else:
                lines.append(f"### {i}. [{title}]({url})")
                lines.append(f"> {tagline}")
                lines.append(f"🔥 {heat}")
            lines.append("")

            analysis_brief = item.get("analysis_brief", "")
            if not analysis_brief:
                for field in ("summary_cn", "translation"):
                    val = item.get(field)
                    if isinstance(val, str) and val.strip():
                        analysis_brief = val.strip()
                        item["analysis_brief"] = analysis_brief
                        break
            if not analysis_brief and tagline and LLM_AVAILABLE and item.get("starhub"):
                expanded = expand_product_tagline(
                    title, tagline, _router=_BRIEF_ROUTER, _budget=_BRIEF_BUDGET,
                )
                if expanded:
                    analysis_brief = expanded
                    item["analysis_brief"] = expanded
            if analysis_brief:
                lines.append(f"> ⚡ {analysis_brief}")
                lines.append("")
            if grok_review:
                lines.append(f"> **🦅 Grok 舆情核查**: {grok_review}")
                lines.append("")
    else:
        lines.append("*暂无数据 (Product Hunt API 可能需要配置)*\n")

    # --- Social (X/Twitter) ---
    lines.append("## 🐦 社交热议 (Social)")
    lines.append("> X (Twitter) - AI/Tech Discussions\n")

    if intel.get("social"):
        for item in intel["social"]:
            if item.get("type") == "markdown_report":
                lines.append(f"> 来源: {item.get('source', 'X')}\n")
                lines.append(item.get("content", "*无内容*"))
                lines.append("")
            else:
                title = item.get("title", "")
                url = item.get("url", "#")
                author = item.get("author", "")
                heat = item.get("heat", "")

                lines.append(f"### {author}")
                lines.append(f"> {title}")
                lines.append(f"❤️ {heat} | 🔗 [Link]({url})")
                lines.append("")
    else:
        lines.append("*暂无数据 (需要配置 XAI_API_KEY)*\n")

    # --- Community ---
    lines.append("## 🗣️ 社区热点 (Community)")
    lines.append("> V2EX 热门\n")

    if community_items:
        for i, item in enumerate(community_items, 1):
            title = item.get("title", "Untitled")
            url = item.get("url", "#")
            heat = item.get("heat", "")

            lines.append(f"### {i}. [{title}]({url})")
            lines.append(f"💬 {heat}")
            if item.get("analysis_brief"):
                lines.append(f"> ⚡ {item['analysis_brief']}")
            lines.append("")
    else:
        lines.append("*暂无数据*\n")



    # --- Insights (HN Top Blogs) ---
    lines.append("## 💡 深度洞察 (Insights)")
    lines.append("> HN Top Blogs + MIT Technology Review — 精选深度分析\n")

    if insights_items:
        for i, item in enumerate(insights_items, 1):
            title = item.get("title", "Untitled")
            url = item.get("url", "#")
            author = item.get("author", "")
            time_str = item.get("time", "")
            rss_content = item.get("content", "").replace("\n", " ")

            # Jina full-content analysis
            source_text = ""
            if JINA_AVAILABLE and url and url.startswith("http"):
                logger.info(f"[Insights {i}] Fetching full content via Jina...")
                full_content = fetch_full_content(url)
                if full_content and len(full_content) > 200:
                    source_text = full_content
                    logger.info(f"[Insights {i}] Using Jina full content ({len(source_text)} chars)")

            if not source_text and rss_content:
                source_text = rss_content
                logger.debug(f"[Insights {i}] Fallback to RSS content ({len(source_text)} chars)")

            brief_cn = ""
            detail_cn = ""
            if source_text and LLM_AVAILABLE:
                brief_cn = summarize_blog_article(source_text, mode="brief", _router=_BRIEF_ROUTER, _budget=_BRIEF_BUDGET)
                time.sleep(GEMINI_RATE_LIMIT_DELAY)
                detail_cn = summarize_blog_article(source_text, mode="detail", _router=_BRIEF_ROUTER, _budget=_BRIEF_BUDGET)

            lines.append(f"### {i}. [{title}]({url})")
            if brief_cn:
                lines.append(f"> ⚡ {brief_cn}")

            lines.append(f"📍 {author}{' | 📅 ' + time_str if time_str else ''}")

            if detail_cn:
                lines.append("")
                lines.append(f"**详情:** {detail_cn}")

            lines.append("")
    else:
        lines.append("*暂无数据 (HN Blogs 传感器不可用)*\n")

        

    provenance = intel.get("_provenance", {}).get("starhub", {})
    if provenance.get("enabled") and provenance.get("snapshot_sources"):
        selected = {
            category: sum(1 for item in items if item.get("starhub"))
            for category, items in selected_by_category.items()
        }
        selected = {category: count for category, count in selected.items() if count}
        analysis = Counter(
            item.get("_analysis_stage", "unprocessed")
            for items in selected_by_category.values()
            for item in items
            if item.get("starhub")
        )
        provenance["selected"] = selected
        provenance["analysis"] = dict(analysis)

        # Task 7: report-level provider/fallback counts
        starhub_items = [
            item for items in selected_by_category.values()
            for item in items if item.get("starhub")
        ]
        selected_count = len(starhub_items)
        fallback_count = sum(
            1 for item in starhub_items
            if item.get("_analysis_stage") == "rss_fallback"
        )
        provider_counts = Counter(
            item.get("_provider") or "none"
            for item in starhub_items
        )
        provenance["selected_count"] = selected_count
        provenance["fallback_count"] = fallback_count

        logger.info(
            "[PROVENANCE] selected_count=%d fallback_count=%d providers=%s stages=%s",
            selected_count, fallback_count, dict(provider_counts), dict(analysis),
        )
        logger.info("[TRACE] StarHub selected=%s analysis=%s", selected, dict(analysis))
        routed = provenance.get("routed", {})
        routed_text = ", ".join(f"{k}={v}" for k, v in sorted(routed.items()))
        lines.append(f"**分析溯源:** StarHub {provenance['snapshot_sources']} 源 / {provenance['snapshot_items']} 条 → 适配 {provenance['adapted_items']} 条 → 路由 {routed_text}")
        lines.append("")
    lines.append("---")
    lines.append("*报告由 Unified Intelligence Engine V2 自动生成 (含 StarHub 716 RSS 源分析)*")

    return "\n".join(lines)


__all__ = ['generate_report']
