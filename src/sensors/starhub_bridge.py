#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""StarHub Bridge Sensor — 快照桥接模块（精简版）
下载 StarHub 716 RSS 快照并适配为 Intel_Briefing 标准传感器格式。
所有分析、去重、报告生成均由 Intel_Briefing 现有管线处理。
"""
import json, logging, urllib.request
from datetime import datetime

logger = logging.getLogger("starhub_bridge")

# ── 分类映射: StarHub cat → Intel_Briefing 现有 7 分类 ──
CAT_MAP = {
    "ai": "tech_trends", "tech": "tech_trends", "cn_tech": "tech_trends",
    "news": "tech_trends",
    "dev": "insights", "insights": "insights",
    "podcast": "insights", "youtube": "insights",
    "wechat": "capital_flow",
    "horizon": "research",
}

def _safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))

def fetch_starhub_snapshot(snapshot_url, timeout=30):
    """下载 StarHub rss_api_snapshot.json。失败返回 None。"""
    try:
        _safe_print(f"  [*] Fetching StarHub snapshot from {snapshot_url[:60]}...")
        req = urllib.request.Request(snapshot_url, headers={
            "User-Agent": "Intel-Briefing/2.0 (+https://kwei168.github.io/Intel_Briefing/)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        sources = data.get("sources", [])
        total = sum(len(s.get("items", [])) for s in sources)
        _safe_print(f"  \u2705 StarHub: {len(sources)} sources, {total} items")
        gen_at = data.get("t", "")
        if gen_at:
            try:
                gt = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
                age_h = (datetime.now(gt.tzinfo) - gt).total_seconds() / 3600
                tag = "\u26a0\ufe0f" if age_h > 48 else "\u2705"
                _safe_print(f"  {tag} Snapshot age: {age_h:.1f}h")
            except (ValueError, TypeError):
                pass
        return data
    except Exception as e:
        _safe_print(f"  \u274c StarHub fetch failed: {e}")
        logger.warning("StarHub snapshot fetch failed: %s", e)
        return None

def adapt_to_intel(snapshot, max_per_cat=50):
    """将 StarHub 快照适配为 Intel_Briefing 标准格式。
    返回 dict[category, list[items]]。只负责格式映射，不做分析/去重。
    """
    if not snapshot or not snapshot.get("sources"):
        return {}
    result = {}
    for src in snapshot["sources"]:
        ib_cat = CAT_MAP.get(src.get("cat", "tech"), "tech_trends")
        src_name = src.get("name", "Unknown")
        src_color = src.get("color", "#888")
        for item in src.get("items", []):
            title, url = item.get("t", ""), item.get("u", "")
            if not title or not url:
                continue
            result.setdefault(ib_cat, []).append({
                "title": title, "url": url,
                "summary": (item.get("s") or "")[:500],
                "time": (item.get("d") or "")[:16],
                "category": src_name, "source_color": src_color,
            })
    for cat in result:
        result[cat] = result[cat][:max_per_cat]
    total = sum(len(v) for v in result.values())
    cats = [k for k, v in result.items() if v]
    _safe_print(f"  \u2705 StarHub adapted: {total} items → {len(cats)} categories")
    return result
