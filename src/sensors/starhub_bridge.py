#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
StarHub Bridge Sensor — 快照桥接模块
从 StarHub 项目的 rss_api_snapshot.json 获取 716 个 RSS 信源的聚合数据，
适配为 Intel_Briefing 的分类结构，并提取分析洞察（关键词/话题/信源活跃度）。

数据流向: StarHub (数据供给方) → Intel_Briefing (分析消费方)
协议: 单次 HTTP GET 下载预构建快照 (~15MB)
"""

import os
import sys
import re
import json
import math
import logging
import collections
import urllib.request
from datetime import datetime, timedelta

logger = logging.getLogger("starhub_bridge")

# ── 分类映射: StarHub cat → Intel_Briefing category ──
CAT_MAP = {
    "ai":       "tech_trends",
    "tech":     "tech_trends",
    "cn_tech":  "tech_trends",
    "dev":      "insights",
    "news":     "global_news",
    "podcast":  "media_radar",
    "wechat":   "cn_media",
    "youtube":  "media_radar",
    "insights": "insights",
    "horizon":  "horizon",
}

# ── 中英文停用词 (轻量版) ──
_STOP_ZH = set("的了是在我有和就不人都一个上也这到说们为你会对他就是那要被她它自己"
               "什么没有可以已经还是或者虽然但是因此如果而且并且以及不过然后所以因为"
               "于在与及等和而中从把被让给向由按照根据为了因作为以更最非常再又还已经"
               "进行开展实施推进加强深化重要关键核心发展建设改革完善优化提升推动促进")
_STOP_EN = set(("the a an is are was were be been being have has had do does did will "
                "would shall should may might can could i me my we our you your he him "
                "his she her it its they them their this that these those there here what "
                "which who whom whose when where why how and or but not no nor so yet for "
                "to of in on at by with from as into about through during before after "
                "above below between under again further then once also just than very too "
                "only same other some such all each every both few more most new old first "
                "last long great little own right big high small next early young important "
                "public bad able https http com org net edu gov io co www id item html "
                "href src png jpg gif css js xml json nbsp div span class amp lt gt quot").split())
_STOP = _STOP_ZH | _STOP_EN


def _safe_print(msg):
    """Windows GBK-safe print."""
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
        total_items = sum(len(s.get("items", [])) for s in sources)
        _safe_print(f"  \u2705 StarHub snapshot: {len(sources)} sources, {total_items} items")

        # 检查数据新鲜度 (超过 48h 警告)
        gen_at = data.get("t", "")
        if gen_at:
            try:
                gen_time = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
                age_hours = (datetime.now(gen_time.tzinfo) - gen_time).total_seconds() / 3600
                if age_hours > 48:
                    _safe_print(f"  \u26a0\ufe0f StarHub snapshot is {age_hours:.0f}h old (>48h)")
                else:
                    _safe_print(f"  \u2705 Snapshot age: {age_hours:.1f}h")
            except (ValueError, TypeError):
                pass

        return data
    except Exception as e:
        _safe_print(f"  \u274c StarHub snapshot fetch failed: {e}")
        logger.warning("StarHub snapshot fetch failed: %s", e)
        return None


def adapt_to_intel(snapshot, max_per_cat=50):
    """将 StarHub sources[] 映射为 Intel_Briefing intel{} 格式。

    字段映射: t->title, u->url, s->summary, d->time
    按 cat 字段分组到 Intel_Briefing 分类。
    """
    if not snapshot or not snapshot.get("sources"):
        return {}

    intel = {
        "tech_trends": [],
        "capital_flow": [],
        "product_gems": [],
        "community": [],
        "research": [],
        "social": [],
        "insights": [],
        # 新增分类
        "global_news": [],
        "media_radar": [],
        "cn_media": [],
        "horizon": [],
    }

    for src in snapshot["sources"]:
        cat = src.get("cat", "tech")
        ib_cat = CAT_MAP.get(cat, "tech_trends")  # 未知分类兜底到 tech_trends
        src_name = src.get("name", "Unknown")
        src_color = src.get("color", "#888")

        for item in src.get("items", []):
            title = item.get("t", "")
            url = item.get("u", "")
            summary = item.get("s", "")
            pub_date = item.get("d", "")

            if not title or not url:
                continue

            intel[ib_cat].append({
                "title": title,
                "url": url,
                "summary": summary[:500] if summary else "",
                "time": pub_date[:16] if pub_date else "",
                "category": src_name,
                "source_color": src_color,
            })

    # 截断每个分类的条目数
    for cat in intel:
        if len(intel[cat]) > max_per_cat:
            intel[cat] = intel[cat][:max_per_cat]

    total = sum(len(v) for v in intel.values())
    cats_with_data = [k for k, v in intel.items() if v]
    _safe_print(f"  \u2705 StarHub adapted: {total} items across {len(cats_with_data)} categories")
    return intel


def dedup_with_sensors(intel, sensor_intel):
    """将 StarHub 数据与传感器数据去重合并。传感器数据优先。"""
    for cat in intel:
        existing_urls = set()
        # 收集传感器已有的 URL
        for item in sensor_intel.get(cat, []):
            u = item.get("url", "")
            if u:
                existing_urls.add(u)
        # 过滤 StarHub 数据中的重复
        new_items = []
        for item in intel.get(cat, []):
            if item.get("url", "") not in existing_urls:
                new_items.append(item)
                existing_urls.add(item.get("url", ""))
        intel[cat] = new_items
    return intel


# ── 分析功能 ──

def _tokenize(text):
    """简易分词: 中文按字, 英文按词, 过滤停用词。"""
    tokens = []
    # 英文词
    for w in re.findall(r'[a-zA-Z][a-zA-Z0-9_\-]+', text.lower()):
        if w not in _STOP and len(w) > 2:
            tokens.append(w)
    # 中文连续 2-4 字 ngram
    cn_chars = re.findall(r'[\u4e00-\u9fff]+', text)
    for seg in cn_chars:
        for n in (2, 3, 4):
            for i in range(len(seg) - n + 1):
                gram = seg[i:i+n]
                if not any(c in _STOP for c in gram):
                    tokens.append(gram)
    return tokens


def extract_keywords(snapshot, top_n=30):
    """从 StarHub 快照提取 TF-IDF 关键词。返回 {global: [...], by_cat: {...}}。"""
    if not snapshot or not snapshot.get("sources"):
        return {"global": [], "by_cat": {}}

    all_tokens = []
    cat_tokens = collections.defaultdict(list)

    for src in snapshot["sources"]:
        cat = src.get("cat", "tech")
        for item in src.get("items", []):
            title = item.get("t", "")
            if not title:
                continue
            tokens = _tokenize(title)
            all_tokens.extend(tokens)
            cat_tokens[cat].extend(tokens)

    # TF 统计
    tf = collections.Counter(all_tokens)
    total = sum(tf.values())
    # 简易 TF 评分 (频率 * log(频率))
    scored = []
    for word, count in tf.items():
        if count < 3:
            continue
        score = count * math.log(1 + count)
        scored.append((word, score))
    scored.sort(key=lambda x: -x[1])

    global_kw = scored[:top_n]

    # 按分类
    by_cat = {}
    for cat, tokens in cat_tokens.items():
        cat_tf = collections.Counter(tokens)
        cat_scored = []
        for word, count in cat_tf.items():
            if count < 2:
                continue
            score = count * math.log(1 + count)
            cat_scored.append((word, score))
        cat_scored.sort(key=lambda x: -x[1])
        if cat_scored:
            by_cat[cat] = cat_scored[:10]

    return {"global": global_kw, "by_cat": by_cat}


def extract_source_activity(snapshot, top_n=20):
    """统计每个 StarHub 源的文章数量。返回 top-N 活跃源。"""
    if not snapshot or not snapshot.get("sources"):
        return []

    activity = []
    for src in snapshot["sources"]:
        n = len(src.get("items", []))
        if n > 0:
            activity.append({
                "name": src.get("name", "Unknown"),
                "cat": src.get("cat", "tech"),
                "count": n,
                "color": src.get("color", "#888"),
            })
    activity.sort(key=lambda x: -x["count"])
    return activity[:top_n]


def extract_topics(snapshot, min_cluster=3, max_topics=15):
    """基于标题 token 重叠度做简易话题聚类。"""
    if not snapshot or not snapshot.get("sources"):
        return []

    # 收集所有标题及其分类
    titles_by_cat = collections.defaultdict(list)
    for src in snapshot["sources"]:
        cat = src.get("cat", "tech")
        for item in src.get("items", []):
            title = item.get("t", "")
            url = item.get("u", "")
            if title and len(title) >= 4:
                titles_by_cat[cat].append({
                    "title": title, "url": url, "cat": cat,
                    "tokens": set(_tokenize(title)),
                })

    # 对每个分类做聚类
    all_clusters = []
    for cat, articles in titles_by_cat.items():
        if len(articles) < min_cluster:
            continue

        # 简易聚类: 贪心合并
        used = set()
        clusters = []
        for i, art_i in enumerate(articles):
            if i in used:
                continue
            cluster = [art_i]
            used.add(i)
            for j in range(i + 1, len(articles)):
                if j in used:
                    continue
                overlap = len(art_i["tokens"] & articles[j]["tokens"])
                if overlap >= 2:
                    cluster.append(articles[j])
                    used.add(j)
            if len(cluster) >= min_cluster:
                # 提取话题标签: 取簇内最常见的 token
                all_tokens = collections.Counter()
                for a in cluster:
                    all_tokens.update(a["tokens"])
                # 过滤过于通用的词
                label_tokens = [w for w, _ in all_tokens.most_common(5)
                                if len(w) >= 2 and w not in _STOP]
                label = " ".join(label_tokens[:3]) if label_tokens else cat
                clusters.append({
                    "label": label,
                    "cat": cat,
                    "count": len(cluster),
                    "articles": [{"title": a["title"], "url": a["url"]}
                                 for a in cluster[:5]],
                })

        all_clusters.extend(clusters)

    # 按簇大小排序, 取 top-N
    all_clusters.sort(key=lambda x: -x["count"])
    return all_clusters[:max_topics]


def run_full_analysis(snapshot):
    """执行完整分析流水线。返回分析数据字典。"""
    _safe_print("  [*] Running StarHub analysis pipeline...")
    t0 = __import__("time").time()

    keywords = extract_keywords(snapshot)
    activity = extract_source_activity(snapshot)
    topics = extract_topics(snapshot)

    elapsed = __import__("time").time() - t0
    _safe_print(f"  \u2705 Analysis done in {elapsed:.1f}s: "
                f"{len(keywords.get('global', []))} keywords, "
                f"{len(topics)} topics, "
                f"{len(activity)} active sources")

    return {
        "keywords": keywords,
        "activity": activity,
        "topics": topics,
        "total_sources": len(snapshot.get("sources", [])) if snapshot else 0,
        "total_items": sum(len(s.get("items", []))
                          for s in (snapshot or {}).get("sources", [])),
    }
