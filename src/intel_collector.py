#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intel Collector - 并发数据采集模块 (V2)
负责从所有传感器收集情报数据

Phase 1 重构：
- ThreadPoolExecutor 并发（vs Phase 0 串行）
- 保留 Batch 依赖顺序：Batch1 并发采集 → Batch2 依赖结果的 Grok 调用
- 完整运行时预算报告
"""

import sys
import os
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from threading import Lock

# --- Logging Setup ---
logger = logging.getLogger("intel_collector")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# --- Imports: External (internalized in src/external/) ---
try:
    from src.external.fetch_news import (
        fetch_hackernews,
        fetch_github,
        fetch_36kr,
        fetch_wallstreetcn,
        fetch_v2ex,
        filter_items
    )
except ImportError as e:
    print(f"[ERROR] Cannot import fetch_news from src/external/: {e}")
    sys.exit(1)

# --- Imports: Local Sensors ---
try:
    from src.sensors.product_hunt import fetch_trending_products
    PH_AVAILABLE = True
except ImportError:
    PH_AVAILABLE = False
    print("[WARN] Product Hunt sensor not available, skipping.")

try:
    from src.sensors.arxiv_ai import fetch_ai_papers
    ARXIV_AVAILABLE = True
except ImportError:
    ARXIV_AVAILABLE = False
    print("[WARN] ArXiv sensor not available, skipping.")

try:
    from src.sensors.x_grok_sensor import fetch_grok_intel
    GROK_AVAILABLE = True
except ImportError:
    GROK_AVAILABLE = False
    print("[WARN] Grok (X/Twitter) sensor not available, skipping.")

try:
    from src.sensors.hf_daily_papers import fetch_hf_daily_papers
    HF_PAPERS_AVAILABLE = True
except ImportError:
    HF_PAPERS_AVAILABLE = False
    print("[WARN] HF Daily Papers sensor not available, skipping.")

try:
    from src.sensors.hn_blogs import fetch_hn_blogs
    HN_BLOGS_AVAILABLE = True
except ImportError:
    HN_BLOGS_AVAILABLE = False
    print("[WARN] HN Top Blogs sensor not available, skipping.")

try:
    from src.sensors.techcrunch_rss import fetch_techcrunch
    TC_AVAILABLE = True
except ImportError:
    TC_AVAILABLE = False
    print("[WARN] TechCrunch sensor not available, skipping.")

try:
    from src.sensors.mit_tech_review import fetch_mit_review
    MIT_TR_AVAILABLE = True
except ImportError:
    MIT_TR_AVAILABLE = False
    print("[WARN] MIT Technology Review sensor not available, skipping.")

# --- StarHub RSS Bridge ---
try:
    from src.sensors.starhub_bridge import fetch_starhub_snapshot, adapt_to_intel
    STARHUB_AVAILABLE = True
except ImportError:
    STARHUB_AVAILABLE = False
    print("[WARN] StarHub bridge not available, skipping.")

# --- Anti-Hallucination: Link Verifier ---
try:
    from src.utils.verifier import verify_link
    VERIFIER_AVAILABLE = True
except ImportError:
    VERIFIER_AVAILABLE = False
    print("[WARN] Link verifier not available, skipping hallucination checks.")


# === Thread-safe helpers ===
_print_lock = Lock()

def _safe_print(msg: str):
    """Thread-safe print."""
    with _print_lock:
        print(msg)


def _dedup_items(items: list[dict]) -> list[dict]:
    """Deduplicate intel items by normalized title.
    
    Items with empty titles are always kept (no key to dedup on).
    """
    seen = set()
    result = []
    for item in items:
        title = item.get("title", "").strip().lower()
        if not title or title not in seen:
            if title:
                seen.add(title)
            result.append(item)
    return result


def _route_starhub_item(item: dict) -> str:
    """按来源语义将已适配条目路由到现有日报栏目。"""
    source = str(item.get("category", ""))
    source_cat = str(item.get("source_category", ""))
    source_url = str(item.get("source_url", ""))
    text = f"{source} {source_cat} {source_url}".lower()
    base = {
        "ai": "tech_trends", "tech": "tech_trends", "cn_tech": "tech_trends",
        "news": "tech_trends", "wechat": "tech_trends",
        "dev": "community", "insights": "insights", "podcast": "insights",
        "youtube": "insights", "horizon": "research",
    }.get(source_cat, "tech_trends")
    if any(term in text for term in ("product hunt", "producthunt")):
        return "product_gems"
    if any(term in text for term in ("arxiv", "paper", "research", "nature", "quanta", "science", "hugging face", "hf daily")):
        return "research"
    if any(term in text for term in ("36kr", "36氪", "wallstreet", "capital", "invest", "finance", "venture", "fundrais", "economy", "business")):
        return "capital_flow"
    if any(term in text for term in ("v2ex", "hacker news", "reddit", "nodeseek", "zhihu", "forum", "stack overflow")):
        return "community"
    if any(term in text for term in ("x/twitter", "twitter", "weibo", "微博")):
        return "social"
    if any(term in text for term in ("blog", "newsletter", "podcast", "youtube", "mit technology review", "techcrunch")):
        return "insights"
    return base


def _merge_starhub_items(intel: dict, adapted: dict) -> Counter:
    """把适配结果送入现有栏目，并返回路由审计计数。"""
    routed = Counter()
    for items in adapted.values():
        for item in items:
            category = _route_starhub_item(item)
            item["intel_category"] = category
            if category == "product_gems":
                item.setdefault("tagline", item.get("summary", ""))
                item.setdefault("heat", "StarHub RSS")
                item.setdefault("topics", ["starhub", "rss"])
            if category in intel:
                intel[category].append(item)
                routed[category] += 1
    return routed


def validate_grok_report(markdown_content: str):
    """
    Anti-Hallucination Layer: Extract and validate all links in Grok's output.
    Appends warning to invalid links.
    """
    if not VERIFIER_AVAILABLE:
        return markdown_content
    
    link_pattern = r'\[([^\]]+)\]\((https?://[^\)]+)\)'
    matches = re.findall(link_pattern, markdown_content)
    
    if not matches:
        return markdown_content
    
    _safe_print(f"  [*] Validating {len(matches)} links from Grok output...")
    validated_content = markdown_content
    
    for title, url in matches:
        skip_domains = ['twitter.com', 'x.com', 'weibo.com', 'xiaohongshu.com']
        if any(domain in url for domain in skip_domains):
            continue
        
        is_valid = verify_link(url)
        if not is_valid:
            old_link = f"[{title}]({url})"
            new_link = f"[{title}]({url}) **(⚠️ 链接验证失败/404)**"
            validated_content = validated_content.replace(old_link, new_link)
            _safe_print(f"    ❌ INVALID: {url}")
        else:
            _safe_print(f"    ✅ Valid: {url[:50]}...")
    
    return validated_content


# =====================================================================
# Sensor Task Definitions — each returns (sensor_name, category, items)
# =====================================================================

def _fetch_hn(limit):
    items = fetch_hackernews(limit=limit)
    return "Hacker News", "tech_trends", [
        {**item, "category": "Hacker News"} for item in items
    ]

def _fetch_github(limit):
    items = fetch_github(limit=limit)
    return "GitHub Trending", "tech_trends", [
        {**item, "category": "GitHub"} for item in items
    ]

def _fetch_36kr(limit):
    items = fetch_36kr(limit=limit)
    return "36Kr", "capital_flow", [
        {**item, "category": "36Kr"} for item in items
    ]

def _fetch_wallstreetcn(limit):
    items = fetch_wallstreetcn(limit=limit)
    return "WallStreetCN", "capital_flow", [
        {**item, "category": "WallStreetCN"} for item in items
    ]

def _fetch_v2ex(limit):
    items = fetch_v2ex(limit=limit)
    return "V2EX", "community", [
        {**item, "category": "V2EX"} for item in items
    ]

def _fetch_arxiv(limit):
    papers = fetch_ai_papers(limit=limit)
    return "ArXiv", "research", [
        {
            "source": "ArXiv", "category": "ArXiv",
            "title": p.title, "url": p.url,
            "authors": ", ".join(p.authors[:2]),
            "time": p.published,
            "categories": ", ".join(p.categories[:2]),
            "summary": p.summary
        } for p in papers
    ]

def _fetch_hf_papers(limit):
    papers = fetch_hf_daily_papers(limit=limit)
    return "HF Papers", "research", [
        {
            "source": "HF Daily Papers", "category": "HF Papers",
            "title": p.title, "url": p.url,
            "authors": ", ".join(p.authors[:2]),
            "time": p.published,
            "categories": ", ".join(p.categories[:2]),
            "summary": p.summary
        } for p in papers
    ]

def _fetch_techcrunch(limit):
    articles = fetch_techcrunch(limit=limit)
    return "TechCrunch", "tech_trends", [
        {
            "source": "TechCrunch", "category": "TechCrunch",
            "title": a.title, "url": a.url,
            "heat": a.heat, "time": a.pub_date,
            "detail": a.description
        } for a in articles
    ]

def _fetch_hn_blogs(_limit):
    articles = fetch_hn_blogs(limit=5)
    return "HN Blogs", "insights", [
        {
            "source": "HN Top Blogs", "category": "HN Blogs",
            "title": a.title, "url": a.url,
            "author": a.source, "time": a.pub_date,
            "content": a.content
        } for a in articles
    ]

def _fetch_mit_tr(_limit):
    articles = fetch_mit_review(limit=5)
    return "MIT TR", "insights", [
        {
            "source": "MIT Technology Review", "category": "MIT TR",
            "title": a.title, "url": a.url,
            "author": a.author, "time": a.pub_date,
            "content": a.description
        } for a in articles
    ]

def _fetch_product_hunt(limit):
    products = fetch_trending_products(limit)
    results = []
    for p in products:
        results.append({
            "source": "Product Hunt", "category": "Product Hunt",
            "title": p.name, "url": p.url,
            "heat": f"{p.votes_count} votes",
            "time": "Today", "tagline": p.tagline,
            "topics": p.topics or [],   # Critical: pass through for anti-hallucination
            "grok_review": None
        })
    return "Product Hunt", "product_gems", results


# =====================================================================
# Main Orchestrator
# =====================================================================

def fetch_all_sources(limit_per_source: int = 10) -> dict:
    """Fetch from all configured sources using concurrent execution.
    
    Architecture:
        Batch 1 — All independent sensors run in parallel (ThreadPoolExecutor)
        Batch 2 — Grok sentiment + X scan (depends on PH results, runs serial)
    """
    _timings = {}
    _total_start = time.time()
    
    intel = {
        "tech_trends": [],
        "capital_flow": [],
        "product_gems": [],
        "community": [],
        "research": [],
        "social": [],
        "insights": [],

    }
    
    # ========== BATCH 1: Concurrent Independent Sensors ==========
    batch1_tasks = [
        ("Hacker News",      _fetch_hn,          True),
        ("GitHub Trending",  _fetch_github,       True),
        ("36Kr",             _fetch_36kr,         True),
        ("WallStreetCN",     _fetch_wallstreetcn, True),
        ("V2EX",             _fetch_v2ex,         True),
    ]
    
    # Conditionally add optional sensors
    if HF_PAPERS_AVAILABLE:
        batch1_tasks.append(("HF Papers", _fetch_hf_papers, True))
    if ARXIV_AVAILABLE:
        batch1_tasks.append(("ArXiv", _fetch_arxiv, True))
    if TC_AVAILABLE:
        batch1_tasks.append(("TechCrunch", _fetch_techcrunch, True))
    if HN_BLOGS_AVAILABLE:
        batch1_tasks.append(("HN Blogs", _fetch_hn_blogs, True))
    if MIT_TR_AVAILABLE:
        batch1_tasks.append(("MIT TR", _fetch_mit_tr, True))
    if PH_AVAILABLE:
        batch1_tasks.append(("Product Hunt", _fetch_product_hunt, True))
    
    print(f"[*] Batch 1: Launching {len(batch1_tasks)} sensors in parallel...")
    
    with ThreadPoolExecutor(max_workers=min(len(batch1_tasks), 8)) as executor:
        future_to_name = {}
        for name, func, _ in batch1_tasks:
            _safe_print(f"  → {name}")
            future = executor.submit(_timed_fetch, name, func, limit_per_source, _timings)
            future_to_name[future] = name
        
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                sensor_name, category, items = future.result()
                if items:
                    intel[category].extend(items)
                    _safe_print(f"  ✅ {sensor_name}: {len(items)} items")
                else:
                    _safe_print(f"  ⚠️ {sensor_name}: 0 items")
            except Exception:
                logger.exception("Sensor %s FAILED", name)
    

    # ========== StarHub RSS Merge (post-Batch 1, pre-Batch 2) ==========
    starhub_provenance = {
        "enabled": False, "snapshot_sources": 0, "snapshot_items": 0,
        "adapted_items": 0, "routed": {},
    }
    if STARHUB_AVAILABLE:
        try:
            from src.config import STARHUB_BRIDGE_ENABLED, STARHUB_SNAPSHOT_URL
            starhub_provenance["enabled"] = STARHUB_BRIDGE_ENABLED
            if STARHUB_BRIDGE_ENABLED:
                print(f"\n[*] StarHub RSS bridge: merging into existing categories...")
                _t = time.time()
                snapshot = fetch_starhub_snapshot(STARHUB_SNAPSHOT_URL)
                if snapshot:
                    sources = snapshot.get("sources", [])
                    starhub_provenance["snapshot_sources"] = len(sources)
                    starhub_provenance["snapshot_items"] = sum(len(s.get("items", [])) for s in sources)
                    adapted = adapt_to_intel(snapshot)
                    starhub_provenance["adapted_items"] = sum(len(v) for v in adapted.values())
                    routed = _merge_starhub_items(intel, adapted)
                    starhub_provenance["routed"] = dict(routed)
                    _safe_print(f"  [TRACE] StarHub route: {dict(routed)}")
                _timings["StarHub Bridge"] = time.time() - _t
            else:
                print("\n[*] StarHub bridge disabled (STARHUB_BRIDGE_ENABLED=false)")
        except Exception as e:
            logger.warning("StarHub bridge failed: %s", e)
            _safe_print(f"  \u26a0\ufe0f StarHub bridge failed: {e}")

    # ========== BATCH 2: Grok (depends on PH results) ==========
    if GROK_AVAILABLE:
        # 2a: Grok Sentiment for Top 3 Product Hunt items
        if intel["product_gems"]:
            print(f"\n[*] Batch 2a: Grok sentiment for top 3 products...")
            _t = time.time()
            for i, product_data in enumerate(intel["product_gems"][:3]):
                try:
                    _safe_print(f"  [*] Grok 舆情核查: {product_data['title']}...")
                    grok_prompt = f"""You are an X (Twitter) analyst. Search X for the product "{product_data['title']}" with tagline "{product_data.get('tagline', '')}".
Provide a market sentiment summary in Simplified Chinese (简体中文), including:
1. Overall sentiment (positive/negative/mixed)
2. 3-5 key findings from real users/developers/founders on X
3. Pros and Cons

Format: Use numbered list. For each finding, mention who said it (e.g., @username or role like "a developer").
Keep it concise but informative. If no data found, say "暂无X平台讨论数据"."""
                    grok_result = fetch_grok_intel(f"PH: {product_data['title']}", override_prompt=grok_prompt)
                    if grok_result and "Error" not in grok_result:
                        intel["product_gems"][i]["grok_review"] = grok_result
                        _safe_print(f"    ✅ Grok returned sentiment for {product_data['title']}")
                    else:
                        _safe_print(f"    ⚠️ Grok returned no data for {product_data['title']}")
                except Exception:
                    logger.exception("Grok PH sentiment failed for %s", product_data['title'])
            _timings["Grok Sentiment"] = time.time() - _t
        
        # 2b: Grok X/Twitter intelligence scan
        print(f"\n[*] Batch 2b: Grok X intelligence scan...")
        _t = time.time()
        try:
            grok_report = fetch_grok_intel("AI Agents, LLM, Tech Startups")
            if grok_report and "Error" not in grok_report:
                validated_report = validate_grok_report(grok_report)
                intel["social"].append({
                    "source": "X (via Grok)",
                    "category": "X/Grok",
                    "content": validated_report,
                    "type": "markdown_report"
                })
                print("  [INFO] Grok returned X intelligence report (links validated).")
            else:
                print(f"  [WARN] Grok returned no data or error.")
        except Exception:
            logger.exception("Grok API failed")
        _timings["X/Grok Scan"] = time.time() - _t
    

    # ========== RUNTIME BUDGET SUMMARY ==========
    _total_elapsed = time.time() - _total_start
    print(f"\n{'='*60}")
    print(f"  ⏱️  RUNTIME BUDGET REPORT")
    print(f"{'='*60}")
    for sensor_name, duration in sorted(_timings.items(), key=lambda x: -x[1]):
        bar = "█" * int(duration / 2) if duration > 0 else ""
        print(f"  {sensor_name:<25s} {duration:6.1f}s  {bar}")
    print(f"  {'─'*45}")
    print(f"  {'TOTAL':<25s} {_total_elapsed:6.1f}s / 900s ({_total_elapsed/900*100:.0f}%)")
    if _total_elapsed > 600:
        print(f"  ⚠️  WARNING: Approaching 15-min GitHub Actions limit!")
    print(f"{'='*60}\n")
    # ========== POST-PROCESSING: Existing deduplication for every section ==========
    dedup_counts = {}
    for category in tuple(intel):
        before = len(intel[category])
        intel[category] = _dedup_items(intel[category])
        dedup_counts[category] = {"before": before, "after": len(intel[category])}
    starhub_provenance["dedup"] = dedup_counts
    intel["_provenance"] = {"starhub": starhub_provenance, "timings": dict(_timings)}
    _safe_print(f"  [TRACE] Final category counts: { {k: len(v) for k, v in intel.items() if isinstance(v, list)} }")
    return intel


def _timed_fetch(name, func, limit, timings_dict):
    """Wrapper that times a sensor fetch and stores the duration."""
    _safe_print(f"  [*] Fetching {name}...")
    start = time.time()
    try:
        result = func(limit)
        elapsed = time.time() - start
        timings_dict[name] = elapsed
        return result
    except Exception as e:
        elapsed = time.time() - start
        timings_dict[name] = elapsed
        raise


__all__ = ['fetch_all_sources', 'validate_grok_report']
