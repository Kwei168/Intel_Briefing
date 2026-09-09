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
    "news": "tech_trends", "wechat": "tech_trends",
    "dev": "community", "insights": "insights",
    "podcast": "insights", "youtube": "insights",
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

def adapt_to_intel(snapshot):
    """将快照字段适配为 Intel_Briefing item；不截断、不分类分析、不去重。"""
    if not snapshot or not snapshot.get("sources"):
        return {}
    result = {}
    valid = 0
    for src in snapshot["sources"]:
        source_cat = src.get("cat", "tech")
        ib_cat = CAT_MAP.get(source_cat, "tech_trends")
        src_name = src.get("name", "Unknown")
        src_color = src.get("color", "#888")
        src_url = src.get("url", "")
        for item in src.get("items", []):
            title, url = item.get("t", ""), item.get("u", "")
            if not title or not url:
                continue
            summary = (item.get("s") or "")[:500]
            adapted = {
                "title": title, "url": url, "summary": summary,
                "content": summary, "time": (item.get("d") or "")[:16],
                "category": src_name, "source_color": src_color,
                "source_url": src_url, "source_category": source_cat,
                "starhub": True,
            }
            # 仅透传快照中已有的预计算字段，空值不写入，交给下游管线复用
            for field in ("summary_cn", "translation", "analysis_brief"):
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    adapted[field] = value
            result.setdefault(ib_cat, []).append(adapted)
            valid += 1
    total = sum(len(v) for v in result.values())
    cats = [k for k, v in result.items() if v]
    _safe_print(f"  \u2705 StarHub adapted: {valid} valid items → {len(cats)} intake categories")
    return result
