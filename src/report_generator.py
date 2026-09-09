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

from src.config import GEMINI_RATE_LIMIT_DELAY

# --- Gemini Translator ---
try:
    from src.utils.gemini_translator import translate_to_chinese, summarize_blog_article, generate_brief, generate_news_brief
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# --- Jina Reader (Full Content Fetcher) ---
try:
    from src.utils.jina_reader import fetch_full_content
    JINA_AVAILABLE = True
except ImportError:
    JINA_AVAILABLE = False
    logger.info("Jina Reader not available, using RSS description only.")

if not GEMINI_AVAILABLE:
    logger.info("Gemini translator not available, using English summaries.")
    def translate_to_chinese(text, max_chars=100):
        return text[:max_chars] + "..." if len(text) > max_chars else text

    def summarize_blog_article(content, mode="brief"):
        return ""

    def generate_brief(content, category="general"):
        return ""

    def generate_news_brief(title, content="", category="tech", _depth=0):
        return ""


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
    """优先使用 Gemini 对 StarHub 摘要做短报；无密钥时保留原始摘要。"""
    if item.get("analysis_brief"):
        item["_analysis_stage"] = "precomputed"
        return item["analysis_brief"]
    content = (item.get("content") or item.get("summary") or "").strip()
    if item.get("starhub") and content and GEMINI_AVAILABLE:
        brief = generate_news_brief(item.get("title", ""), content, category=category)
        if brief:
            item["analysis_brief"] = brief
            item["_analysis_stage"] = "gemini_news_brief"
            return brief
    item["_analysis_stage"] = "rss_fallback" if item.get("starhub") else "source_summary"
    return content[:240] if content else ""


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
            brief_cn = generate_brief(summary, category="research") if summary else ""
            
            # 添加延迟以避免 API 限速
            if GEMINI_AVAILABLE and summary:
                time.sleep(GEMINI_RATE_LIMIT_DELAY)
            
            # 2. Detail: 完整翻译（允许完整输出）
            detail_cn = translate_to_chinese(summary, max_chars=1200) if summary else ""

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
            if source_text and GEMINI_AVAILABLE:
                brief_cn = summarize_blog_article(source_text, mode="brief")
                time.sleep(GEMINI_RATE_LIMIT_DELAY)
                detail_cn = summarize_blog_article(source_text, mode="detail")

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
        logger.info("[TRACE] StarHub selected=%s analysis=%s", selected, dict(analysis))
        routed = provenance.get("routed", {})
        routed_text = ", ".join(f"{k}={v}" for k, v in sorted(routed.items()))
        lines.append(f"**分析溯源:** StarHub {provenance['snapshot_sources']} 源 / {provenance['snapshot_items']} 条 → 适配 {provenance['adapted_items']} 条 → 路由 {routed_text}")
        lines.append("")
    lines.append("---")
    lines.append("*报告由 Unified Intelligence Engine V2 自动生成 (含 StarHub 716 RSS 源分析)*")

    return "\n".join(lines)


__all__ = ['generate_report']
