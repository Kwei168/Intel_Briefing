#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Report Generator - 报告生成模块
负责将情报数据直接转换为完整 HTML 页面。

数据流: fetch_all_sources() → generate_report() → HTML 字符串
不再有 Markdown 或 JSON 中间层。
"""

import re
import sys
import json
import time
import logging
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter, OrderedDict
from datetime import datetime
from html import escape as html_escape

logger = logging.getLogger(__name__)

from src.config import GEMINI_RATE_LIMIT_DELAY

# --- Gemini Translator ---
try:
    from src.utils.gemini_translator import translate_to_chinese, summarize_blog_article, generate_brief, generate_news_brief
    from src.config import GEMINI_API_KEY
    GEMINI_AVAILABLE = bool(GEMINI_API_KEY)
except (ImportError, Exception):
    GEMINI_AVAILABLE = False

# --- Jina Reader (Full Content Fetcher) ---
try:
    from src.utils.jina_reader import fetch_full_content
    JINA_AVAILABLE = True
except ImportError:
    JINA_AVAILABLE = False
    logger.info("Jina Reader not available, using RSS description only.")


# ══════════════════════════════ 免费翻译降级链 ══════════════════════════════
# 当 Gemini API Key 未配置时，使用四端点免费翻译链：
# Google gtx → Bing 网页版 → MyMemory → Google dict-chrome

_TRANS_CACHE = {}
_BING_TOKENS = None


def _has_cn(s):
    """检测文本是否已含中文。"""
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))


def _is_metadata_text(text):
    """检测文本是否为原始 RSS/网页元数据（非正文内容）。"""
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) < 30:
        return True
    metadata_patterns = [
        r'^(Title|URL|Source|Published|Published Time|Warning|Markdown|Author|Date|Description)\s*:',
        r'^URL\s+Source\s*:',
        r'^已发布\s+Time',
    ]
    for pat in metadata_patterns:
        if re.search(pat, stripped, re.IGNORECASE):
            return True
    return False


def _fetch_bing_tokens():
    """访问 bing.com/translator 提取防滥用 token。"""
    global _BING_TOKENS
    if _BING_TOKENS:
        return _BING_TOKENS
    req = urllib.request.Request(
        "https://www.bing.com/translator",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    )
    r = urllib.request.urlopen(req, timeout=15)
    html = r.read().decode("utf-8")
    ig = re.search(r'IG:"([^"]+)"', html)
    iid = re.search(r'data-iid="([^"]+)"', html)
    tok = re.search(r'params_AbusePreventionHelper\s*=\s*\[(\d+),"([^"]+)"', html)
    if not all([ig, iid, tok]):
        raise RuntimeError("Bing token 提取失败")
    _BING_TOKENS = {"IG": ig.group(1), "IID": iid.group(1), "key": tok.group(1), "token": tok.group(2)}
    return _BING_TOKENS


def _bing_translate(text):
    """Bing 网页版翻译（免费，无需 API key）。"""
    try:
        tokens = _fetch_bing_tokens()
    except Exception:
        return None
    data = urllib.parse.urlencode({
        "fromLang": "en", "text": text, "to": "zh-Hans",
        "token": tokens["token"], "key": tokens["key"],
    }).encode("utf-8")
    url = ("https://www.bing.com/ttranslatev3?isVertical=1&" +
           urllib.parse.urlencode({"IG": tokens["IG"], "IID": tokens["IID"]}))
    try:
        req = urllib.request.Request(url, data=data, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.bing.com/translator",
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read().decode("utf-8"))
        if isinstance(result, list) and result:
            trans = result[0].get("translations", [{}])
            if trans:
                return trans[0].get("text", "") or None
        if isinstance(result, dict) and "statusCode" in result:
            global _BING_TOKENS
            _BING_TOKENS = None
    except Exception:
        pass
    return None


def _free_translate(text):
    """免费四端点翻译链：Google gtx → Bing → MyMemory → Google dict-chrome。
    全部失败返回 None。"""
    if not text:
        return None
    hit = _TRANS_CACHE.get(text)
    if hit is not None:
        return hit or None
    result = None

    # 端点 1: Google gtx
    if not result:
        params = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text})
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    "https://translate.googleapis.com/translate_a/single?" + params,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read().decode("utf-8"))
                cand = "".join(seg[0] for seg in data[0] if seg[0]).strip()
                if cand and _has_cn(cand):
                    result = cand
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt == 0:
                    time.sleep(3)
                    continue
                break
            except Exception:
                break

    # 端点 2: Bing 网页版
    if not result:
        cand = _bing_translate(text)
        if cand and _has_cn(cand):
            result = cand

    # 端点 3: MyMemory
    if not result:
        for attempt in range(3):
            try:
                params = urllib.parse.urlencode({"q": text[:480], "langpair": "en|zh-CN"})
                req = urllib.request.Request(
                    "https://api.mymemory.translated.net/get?" + params,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read().decode("utf-8"))
                cand = (data.get("responseData", {}) or {}).get("translatedText", "").strip()
                if cand and _has_cn(cand) and "MYMEMORY WARNING" not in cand:
                    result = cand
                    break
                if attempt < 2:
                    time.sleep(2 ** attempt)
            except Exception:
                if attempt < 2:
                    time.sleep(2 ** attempt)

    # 端点 4: Google dict-chrome
    if not result:
        try:
            params = urllib.parse.urlencode({"client": "dict-chrome", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text})
            req = urllib.request.Request(
                "https://translate.googleapis.com/translate_a/single?" + params,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            cand = "".join(seg[0] for seg in data[0] if seg[0]).strip()
            if cand and _has_cn(cand):
                result = cand
        except Exception:
            pass

    _TRANS_CACHE[text] = result or ""
    return result


def _tr(text):
    """英文文本 → 中文；已含中文或翻译失败时原样返回。间隔 0.3s 防限流。"""
    if not text or _has_cn(text):
        return text
    time.sleep(0.3)
    translated = _free_translate(text)
    return translated or text


def _tr_title(text):
    """翻译标题：保留 arXiv [分类] 前缀。"""
    if not text or _has_cn(text):
        return text
    m = re.match(r"^(\[[^\]]+\]\s*)(.*)$", text)
    if m:
        return m.group(1) + _tr(m.group(2))
    return _tr(text)


# --- Gemini fallback: 当 Gemini 不可用时，使用免费翻译链 ---
if not GEMINI_AVAILABLE:
    logger.info("Gemini API Key 未配置，使用免费翻译降级链。")
    def translate_to_chinese(text, max_chars=100):
        """翻译长文本（论文摘要等），截断到 max_chars。"""
        if not text:
            return ""
        translated = _free_translate(text)
        result = translated or text
        if len(result) > max_chars:
            result = result[:max_chars] + "..."
        return result
    def summarize_blog_article(content, mode="brief"):
        """博客文章摘要：截取前 200 字符并翻译。"""
        if not content:
            return ""
        snippet = content[:200].replace("\n", " ")
        return _tr(snippet)
    def generate_brief(content, category="general"):
        """短摘要：截取前 120 字符并翻译。"""
        if not content:
            return ""
        snippet = content[:120].replace("\n", " ")
        return _tr(snippet)
    def generate_news_brief(title, content="", category="tech", _depth=0):
        """新闻简报：翻译标题+内容前 150 字符。"""
        if not content:
            return _tr(title) if title else ""
        snippet = content[:150].replace("\n", " ")
        return _tr(snippet)


# ══════════════════════════════ HTML 模板 ═════════════════════════════

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>%%TITLE%% - Intel Briefing</title>
<script>try{var _t=localStorage.getItem('wb_starhub_theme_v1')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');document.documentElement.dataset.theme=_t;}catch(e){}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@700;900&family=Noto+Sans+SC:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#faf9f7; --card:#fffdf9; --card-2:#f3efe6; --card-3:#ebe6db;
  --ink:#1c1917; --muted:#5f594c; --faint:#6e685e;
  --line:#ddd6c9; --line-strong:#b9b0a2;
  --brand:#2f5d8a; --brand-strong:#24496e; --brand-line:#b9cde0; --brand-weak:#e7eef4;
  --display:"Noto Serif SC","Georgia","Times New Roman","Songti SC","SimSun","STSong",serif;
  --body:"Noto Sans SC",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  --mono:"IBM Plex Mono","SF Mono","Fira Code","Consolas",monospace;
  --radius:8px;
  --shadow:0 1px 2px rgba(28,25,23,.05);
  --shadow-lift:0 10px 26px rgba(0,0,0,.10),0 2px 4px rgba(0,0,0,.06);
}
[data-theme="dark"] {
  --bg:#161412; --card:#1d1a17; --card-2:#262019; --card-3:#2f2820;
  --ink:#ece7df; --muted:#a59d90; --faint:#a8a090;
  --line:#37312a; --line-strong:#4a4339;
  --brand:#8fb3d9; --brand-strong:#b0cbe6; --brand-line:#3d5a78; --brand-weak:#22303f;
  --shadow:0 1px 2px rgba(0,0,0,.4);
  --shadow-lift:0 10px 26px rgba(0,0,0,.5),0 2px 4px rgba(0,0,0,.4);
}
*,*::before,*::after { box-sizing:border-box; margin:0; padding:0; }
html { scroll-behavior:smooth; scroll-padding-top:112px; }
body { font-family:var(--body); background:var(--bg); color:var(--ink); line-height:1.55; font-size:14px; -webkit-font-smoothing:antialiased; }
a { color:inherit; text-decoration:none; }
button { font-family:inherit; cursor:pointer; border:none; background:none; color:inherit; }
::selection { background:var(--brand-weak); color:var(--ink); }
button:focus-visible, a:focus-visible { outline:2px solid var(--brand); outline-offset:2px; border-radius:var(--radius); }

header { position:sticky; top:0; z-index:40; background:rgba(250,249,247,.94); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px); border-bottom:1px solid var(--line); }
[data-theme="dark"] header { background:rgba(22,20,18,.94); }
.hd { max-width:860px; margin:0 auto; padding:9px 20px; display:flex; align-items:center; gap:12px; }
.hd .logo { display:flex; align-items:center; gap:8px; flex:none; font-family:var(--display); font-weight:900; font-size:16px; }
.hd .logo .sub { font-size:11px; color:var(--muted); font-weight:400; margin-left:2px; font-family:var(--body); }
.hd .logo svg { color:var(--brand); }
.hd .nav-links { display:flex; align-items:center; gap:2px; flex:1; }
.hd .nav-links a { display:inline-flex; align-items:center; gap:5px; white-space:nowrap; padding:5px 12px; border-radius:999px; font-size:12.5px; font-weight:500; border:1px solid transparent; transition:all .15s; }
.hd .nav-links a:hover { background:var(--card); border-color:var(--line); }
.hd .nav-links a.active { background:var(--brand-weak); border-color:var(--brand-line); color:var(--brand-strong); font-weight:600; }
.theme-btn { width:30px; height:30px; border-radius:999px; background:var(--card); border:1px solid var(--line); display:flex; align-items:center; justify-content:center; flex:none; transition:all .15s; }
.theme-btn:hover { border-color:var(--brand-line); color:var(--brand-strong); }
.theme-btn svg { width:14px; height:14px; }
.icon-moon { display:none; }
[data-theme="dark"] .icon-sun { display:none; }
[data-theme="dark"] .icon-moon { display:block; }
.progress { position:absolute; left:0; bottom:-1px; height:2px; background:var(--brand); width:0%; z-index:41; }

.mast { max-width:860px; margin:0 auto; padding:26px 20px 0; text-align:center; }
.mast-rule { display:flex; align-items:center; gap:14px; margin:0 0 6px; }
.mast-rule::before,.mast-rule::after { content:""; flex:1; height:1px; background:var(--line-strong); }
.mast-rule span { font-family:var(--mono); font-size:11px; letter-spacing:.14em; color:var(--muted); font-weight:500; white-space:nowrap; }
.mast-title { font-family:var(--display); font-size:clamp(30px,6vw,44px); font-weight:900; letter-spacing:.05em; line-height:1.2; margin:4px 0 10px; }
.mast-strip { display:flex; flex-wrap:wrap; gap:4px 22px; justify-content:center; align-items:baseline; margin-top:6px; padding:9px 14px; border-top:3px double var(--line-strong); border-bottom:1px solid var(--line-strong); }
.ms-item { font-size:12px; color:var(--muted); }
.ms-item b { font-weight:600; color:var(--faint); font-size:10.5px; letter-spacing:.08em; margin-right:6px; }
.ms-item i { font-family:var(--mono); font-style:normal; color:var(--ink); font-size:11.5px; }

.toc { position:sticky; top:52px; z-index:30; max-width:860px; margin:14px auto 0; padding:8px 20px; background:rgba(250,249,247,.94); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px); border-bottom:1px solid var(--line); display:flex; align-items:center; gap:10px; }
[data-theme="dark"] .toc { background:rgba(22,20,18,.94); }
.toc-label { flex:none; font-family:var(--mono); font-size:9.5px; font-weight:700; letter-spacing:.12em; color:var(--faint); }
.toc-chips { display:flex; gap:6px; overflow-x:auto; padding-bottom:2px; scrollbar-width:none; }
.toc-chips::-webkit-scrollbar { display:none; }
.toc-chip { flex:none; display:inline-flex; align-items:center; gap:5px; padding:3px 11px; border-radius:999px; border:1px solid var(--line); background:var(--card); font-size:12px; color:var(--muted); transition:all .15s; }
.toc-chip:hover { border-color:var(--brand-line); color:var(--brand-strong); background:var(--brand-weak); }
.toc-chip .n { font-family:var(--mono); font-size:10px; opacity:.75; }

.paper { max-width:860px; margin:0 auto; padding:0 20px 56px; }
.article { margin-top:26px; }

.intel-section { margin:34px 0 0; }
.sec-head { display:flex; align-items:center; gap:12px; padding-bottom:10px; border-bottom:1px solid var(--line); margin-bottom:14px; }
.sec-head h2 { display:flex; align-items:center; gap:10px; font-family:var(--display); font-size:clamp(19px,2.6vw,24px); font-weight:700; line-height:1.3; margin:0; }
.sec-head h2::before { content:""; flex:none; width:10px; height:10px; border-radius:2px; background:var(--brand); }
.sec-count { margin-left:auto; flex:none; font-family:var(--mono); font-size:11px; color:var(--faint); }
.sec-src { display:flex; align-items:center; gap:8px; margin:-4px 0 14px; font-family:var(--mono); font-size:11.5px; color:var(--muted); }
.sec-src .src-label { flex:none; font-size:9.5px; font-weight:700; letter-spacing:.1em; color:var(--brand-strong); background:var(--brand-weak); border:1px solid var(--brand-line); border-radius:4px; padding:1px 6px; }

.intel-card { background:var(--card); border:1px solid var(--line); border-radius:var(--radius); padding:14px 16px 12px; margin:0 0 12px; transition:box-shadow .18s, border-color .18s, transform .18s; }
.intel-card:hover { border-color:var(--brand-line); box-shadow:var(--shadow-lift); transform:translateY(-2px); }
.ic-head { display:flex; align-items:flex-start; gap:10px; }
.ic-num { flex:none; font-family:var(--mono); font-size:11px; font-weight:700; color:var(--brand-strong); background:var(--brand-weak); border:1px solid var(--brand-line); border-radius:6px; padding:2px 7px; margin-top:2px; }
.ic-head h3 { font-family:var(--display); font-size:15.5px; font-weight:700; line-height:1.5; margin:0; }
.ic-head h3 a { color:var(--ink); transition:color .15s; border-bottom:none; }
.ic-head h3 a:hover { color:var(--brand-strong); }
.ic-summary { margin:10px 0 0; padding:9px 14px; background:var(--brand-weak); border-left:3px solid var(--brand); border-radius:0 var(--radius) var(--radius) 0; color:var(--muted); font-size:13px; line-height:1.75; }
.ic-summary p { margin:0; }
.ic-detail { margin-top:10px; font-size:13.5px; color:var(--ink); line-height:1.75; }
.ic-foot { display:flex; flex-wrap:wrap; gap:4px 14px; margin-top:10px; padding-top:9px; border-top:1px solid var(--line); font-size:11.5px; color:var(--muted); }
.ic-foot a { color:var(--brand-strong); font-weight:600; border-bottom:none; }
.ic-foot a:hover { text-decoration:underline; text-underline-offset:2px; }

.foot { margin-top:44px; padding-top:14px; border-top:1px solid var(--line); color:var(--muted); font-size:12px; display:flex; flex-wrap:wrap; gap:6px 18px; justify-content:space-between; }
.foot a { color:var(--brand-strong); font-weight:500; }
.foot a:hover { text-decoration:underline; text-underline-offset:2px; }
.back-top { position:fixed; bottom:24px; right:24px; width:40px; height:40px; border-radius:50%; background:var(--card); border:1px solid var(--line); color:var(--muted); display:flex; align-items:center; justify-content:center; cursor:pointer; opacity:0; pointer-events:none; transition:all .2s; z-index:90; box-shadow:0 2px 8px rgba(0,0,0,.08); }
.back-top.show { opacity:1; pointer-events:auto; }
.back-top:hover { color:var(--brand-strong); border-color:var(--brand-line); background:var(--brand-weak); }
.back-top svg { width:18px; height:18px; }

@media (prefers-reduced-motion:reduce) { html { scroll-behavior:auto; } *,*::before,*::after { transition-duration:0s!important; animation-duration:0s!important; } }

@media (max-width:700px) {
  .hd { padding:8px 12px; }
  .hd .nav-links a { padding:5px 9px; font-size:12px; }
  .mast { padding:18px 14px 0; }
  .mast-title { letter-spacing:.02em; }
  .mast-rule span { font-size:10px; letter-spacing:.1em; }
  .mast-rule { gap:8px; }
  .mast-strip { gap:3px 14px; padding:8px 10px; }
  .toc { top:50px; padding:7px 12px; gap:8px; }
  .paper { padding:0 14px 48px; }
  .intel-section { margin:26px 0 0; }
  .sec-head h2 { font-size:18px; }
  .intel-card { padding:12px 13px 10px; }
  .ic-head { gap:8px; }
  .ic-head h3 { font-size:14.5px; }
  .ic-summary { font-size:12.5px; }
  .back-top { bottom:16px; right:16px; }
}
</style>
</head>
<body>

<header>
  <div class="hd">
    <a class="logo" href="../index.html">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="2.2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4"/><path d="M7.8 16.2a6 6 0 0 1 0-8.4"/><path d="M19.1 4.9a10 10 0 0 1 0 14.2"/><path d="M4.9 19.1a10 10 0 0 1 0-14.2"/></svg>
      <span>Intel Briefing<span class="sub">情报日报</span></span>
    </a>
    <nav class="nav-links">
      <a href="../index.html" class="active">日报归档</a>
      <a href="https://kwei168.github.io/StarHub/" target="_blank" rel="noopener">StarHub 收藏台</a>
    </nav>
    <button class="theme-btn" id="btnTheme" title="切换主题 (T)" aria-label="切换明暗主题">
      <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5.3 5.3l1.7 1.7M17 17l1.7 1.7M18.7 5.3 17 7M7 17l-1.7 1.7"/></svg>
      <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z"/></svg>
    </button>
  </div>
  <div class="progress" id="progress"></div>
</header>

<div class="mast">
  <div class="mast-rule"><span>%%DATE%%</span><span>MORNING INTELLIGENCE BRIEFING</span></div>
  <h1 class="mast-title">%%H1%%</h1>
  <div class="mast-strip">%%META%%</div>
</div>

%%TOCNAV%%

<div class="paper">
  <article class="article">
%%CONTENT%%
  </article>
  <footer class="foot">
    <span>由 <a href="https://github.com/Kwei168/Intel_Briefing" target="_blank" rel="noopener">Intel_Briefing</a> 引擎自动生成</span>
    <span>%%DATE%% &middot; 内容版权归原作者所有</span>
    <span><a href="../index.html">返回归档</a> &middot; <a href="https://kwei168.github.io/StarHub/" target="_blank" rel="noopener">StarHub</a></span>
  </footer>
</div>

<button class="back-top" id="backTop" aria-label="回到顶部">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m18 15-6-6-6 6"/></svg>
</button>

<script>
;(function(){
  var btn=document.getElementById('btnTheme');
  function setTheme(t){
    try{ localStorage.setItem('wb_starhub_theme_v1',t); }catch(e){}
    document.documentElement.dataset.theme=t;
  }
  if(btn) btn.onclick=function(){ setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'); };
  document.addEventListener('keydown',function(e){
    var t=e.target, tag=(t.tagName||'').toLowerCase();
    if(tag==='input'||tag==='textarea'||t.isContentEditable) return;
    if(e.key==='t'||e.key==='T'){ setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'); }
  });
  var bar=document.getElementById('progress');
  var backTop=document.getElementById('backTop');
  function onScroll(){
    var st=window.scrollY||document.documentElement.scrollTop||0;
    var max=document.documentElement.scrollHeight-window.innerHeight;
    if(bar) bar.style.width=(max>0?Math.min(100,st/max*100):0)+'%';
    if(backTop) backTop.classList.toggle('show',st>400);
  }
  window.addEventListener('scroll',onScroll,{passive:true});
  onScroll();
  if(backTop) backTop.onclick=function(){ window.scrollTo({top:0,behavior:'smooth'}); };
})();
</script>
</body>
</html>"""


# ══════════════════════════════ 工具函数 ═════════════════════════════

def _esc(s):
    """HTML 转义。"""
    return html_escape(str(s), quote=False)


def _strip_emoji(text):
    """去掉文本中的 emoji 字符（保留中英文、数字、标点）。"""
    return re.sub(
        '['
        '\u200d\u203c\u2049\u20e0-\u20e3\u2122\u2139\u2194-\u21aa'
        '\u231a-\u23ff\u24c2\u25aa-\u25fe\u2600-\u27bf\u2934-\u2935'
        '\u2b05-\u2b55\u3030\u303d\u3297\u3299\ufe0f'
        '\U0001f000-\U0001ffff'
        ']',
        '', text
    ).strip()


def _clean_meta(parts):
    """清理元数据字段：去掉空值、strip emoji。"""
    return [_strip_emoji(str(p)) for p in parts if p and str(p).strip()]


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
    if content and not _is_metadata_text(content):
        return _tr(content[:240])
    return ""


# ══════════════════════════════ HTML 渲染组件 ═════════════════════════════

def _render_card(item):
    """渲染单个条目卡片 HTML — 仅标题+摘要两个核心字段。"""
    parts = ['<div class="intel-card">']
    num = f'<span class="ic-num">{_esc(item["num"])}</span>' if item.get("num") else ''
    title = _esc(item.get("title", ""))
    url = item.get("url", "")
    if url and url != "#":
        title_html = f'<h3><a href="{_esc(url)}" target="_blank" rel="noopener">{title}</a></h3>'
    else:
        title_html = f'<h3>{title}</h3>'
    parts.append(f'<div class="ic-head">{num}{title_html}</div>')
    summary = item.get("summary", "")
    if summary:
        parts.append(f'<blockquote class="ic-summary"><p>{_esc(summary)}</p></blockquote>')
    detail = item.get("detail", "")
    if detail:
        parts.append(f'<div class="ic-detail">{_esc(detail)}</div>')
    parts.append('</div>')
    return ''.join(parts)


def _render_section(sec, idx):
    """渲染一个章节 HTML。"""
    out = [f'<section class="intel-section" id="sec-{idx}">']
    count = len(sec.get("items", []))
    out.append(f'<div class="sec-head"><h2>{_esc(sec["title"])}</h2><span class="sec-count">{count} 条</span></div>')
    if sec.get("src"):
        out.append(f'<div class="sec-src"><span class="src-label">SOURCES</span> {_esc(sec["src"])}</div>')
    items = sec.get("items", [])
    if not items and sec.get("empty_msg"):
        out.append(f'<p style="color:var(--muted);font-size:13px;">{_esc(sec["empty_msg"])}</p>')
    for item in items:
        if item.get("content"):
            out.append(f'<div class="intel-card"><div class="ic-body"><p>{_esc(item["content"])}</p></div></div>')
        else:
            out.append(_render_card(item))
    out.append('</section>')
    return ''.join(out)


def _render_toc(sections):
    """渲染章节目录导航。"""
    chips = ''.join(
        f'<a class="toc-chip" href="#sec-{i}">{_esc(s["title"])}<span class="n">{len(s.get("items",[]))}</span></a>'
        for i, s in enumerate(sections, 1)
    )
    return f'<nav class="toc" aria-label="章节目录"><span class="toc-label">CONTENTS</span><div class="toc-chips">{chips}</div></nav>'


def _render_meta_strip(data):
    """渲染报头信息条。"""
    spans = []
    spans.append(f'<span class="ms-item"><b>生成时间</b><i>{_esc(data.get("generated_time",""))}</i></span>')
    spans.append(f'<span class="ms-item"><b>数据源</b><i>{_esc(data.get("data_sources",""))}</i></span>')
    total = data.get("total_items", 0)
    if total:
        spans.append(f'<span class="ms-item"><b>条目</b><i>{total} 条</i></span>')
    prov = data.get("provenance", "")
    if prov:
        spans.append(f'<span class="ms-item"><b>StarHub</b><i>{_esc(prov)}</i></span>')
    return ''.join(spans)


# ══════════════════════════════ 主入口 ═════════════════════════════

def generate_report(intel: dict, date_str: str) -> str:
    """Generate complete HTML report directly from intelligence data.

    Returns a full HTML string — no intermediate Markdown or JSON.
    """
    tech_items = _select_diverse_items(intel.get("tech_trends", []), 10)
    capital_items = _select_diverse_items(intel.get("capital_flow", []), 10)
    research_items = _select_diverse_items(intel.get("research", []), 5)
    product_items = _select_diverse_items(intel.get("product_gems", []), 8)
    community_items = _select_diverse_items(intel.get("community", []), 5)
    insights_items = _select_diverse_items(intel.get("insights", []), 5)
    selected_by_category = {
        "tech_trends": tech_items, "capital_flow": capital_items,
        "research": research_items, "product_gems": product_items,
        "community": community_items, "social": [], "insights": insights_items,
    }
    for category, selected in selected_by_category.items():
        for item in selected:
            if item.get("starhub"):
                _signal_brief(item, category)

    sections = []

    # --- Tech Trends ---
    items = []
    for i, item in enumerate(tech_items, 1):
        brief = _signal_brief(item, "tech")
        items.append({
            "num": f"{i:02d}",
            "title": _strip_emoji(_tr_title(item.get("title", "Untitled"))),
            "url": item.get("url", "#"),
            "meta": _clean_meta([item.get("category", ""), item.get("heat", ""), item.get("time", "")]),
            "summary": _strip_emoji(brief) if brief else _tr_title(item.get("title", "Untitled")),
        })
    sections.append({"title": "技术趋势 (Tech Trends)", "src": "Hacker News + GitHub Trending", "items": items})

    # --- Capital Flow ---
    items = []
    for i, item in enumerate(capital_items, 1):
        brief = _signal_brief(item, "capital")
        items.append({
            "num": f"{i:02d}",
            "title": _strip_emoji(_tr_title(item.get("title", "Untitled"))),
            "url": item.get("url", "#"),
            "meta": _clean_meta([item.get("category", ""), item.get("time", "")]),
            "summary": _strip_emoji(brief) if brief else _tr_title(item.get("title", "Untitled")),
        })
    sections.append({"title": "资本动向 (Capital Flow)", "src": "36Kr + 华尔街见闻", "items": items})

    # --- Research ---
    items = []
    for i, item in enumerate(research_items, 1):
        summary = item.get("summary", "").replace("\n", " ")
        brief_cn = generate_brief(summary, category="research") if summary else ""
        if GEMINI_AVAILABLE and summary:
            time.sleep(GEMINI_RATE_LIMIT_DELAY)
        detail_cn = translate_to_chinese(summary, max_chars=1200) if summary else ""
        # 确保有摘要：fallback 到翻译后的原文
        final_summary = _strip_emoji(brief_cn) if brief_cn else (_strip_emoji(detail_cn[:200]) if detail_cn else _tr_title(item.get("title", "")))
        items.append({
            "num": f"{i:02d}",
            "title": _strip_emoji(_tr_title(item.get("title", "Untitled"))),
            "url": item.get("url", "#"),
            "meta": _clean_meta([item.get("authors", ""), item.get("time", "")]),
            "summary": final_summary,
            "detail": _strip_emoji(detail_cn) if detail_cn else "",
        })
    sections.append({"title": "学术前沿 (Research)", "src": "ArXiv AI/ML Papers", "items": items})

    # --- Product Gems ---
    items = []
    for i, item in enumerate(product_items, 1):
        is_grok = "grok-fallback" in (item.get("topics") or [])
        items.append({
            "num": f"{i:02d}",
            "title": _strip_emoji(_tr_title(item.get("title", "Untitled"))),
            "url": item.get("url", "#") if not is_grok else "",
            "meta": _clean_meta([item.get("heat", "")]),
            "summary": _strip_emoji(_tr(item.get("tagline", ""))) or _tr_title(item.get("title", "")),
        })
    sections.append({"title": "产品精选 (Product Gems)", "src": "Product Hunt Today", "items": items})

    # --- Social ---
    social_items = []
    if intel.get("social"):
        for item in intel["social"]:
            if item.get("type") == "markdown_report":
                social_items.append({"content": item.get("content", ""), "source": item.get("source", "X")})
            else:
                social_items.append({
                    "num": "",
                    "title": _strip_emoji(_tr(item.get("author", ""))),
                    "url": item.get("url", "#"),
                    "meta": _clean_meta([item.get("heat", "")]),
                    "summary": _strip_emoji(_tr(item.get("title", ""))) or _tr(item.get("author", "")),
                })
    sections.append({
        "title": "社交热议 (Social)", "src": "X (Twitter) - AI/Tech Discussions",
        "items": social_items, "empty_msg": "暂无数据 (需要配置 XAI_API_KEY)",
    })

    # --- Community ---
    items = []
    for i, item in enumerate(community_items, 1):
        items.append({
            "num": f"{i:02d}",
            "title": _strip_emoji(_tr_title(item.get("title", "Untitled"))),
            "url": item.get("url", "#"),
            "meta": _clean_meta([item.get("heat", "")]),
            "summary": _strip_emoji(_tr(item.get("analysis_brief", "") or "") or _tr_title(item.get("title", ""))),
        })
    sections.append({"title": "社区热点 (Community)", "src": "V2EX 热门", "items": items})

    # --- Insights ---
    items = []
    for i, item in enumerate(insights_items, 1):
        url = item.get("url", "#")
        rss_content = item.get("content", "").replace("\n", " ")
        source_text = ""
        if JINA_AVAILABLE and url and url.startswith("http"):
            full_content = fetch_full_content(url)
            if full_content and len(full_content) > 200:
                source_text = full_content
        if not source_text and rss_content:
            source_text = rss_content
        brief_cn = detail_cn = ""
        if source_text:
            brief_cn = summarize_blog_article(source_text, mode="brief")
            if GEMINI_AVAILABLE:
                time.sleep(GEMINI_RATE_LIMIT_DELAY)
                detail_cn = summarize_blog_article(source_text, mode="detail")
        # 确保有摘要：拒绝元数据文本，fallback 到翻译标题
        if brief_cn and not _is_metadata_text(brief_cn):
            final_summary = _strip_emoji(brief_cn)
        elif source_text and not _is_metadata_text(source_text):
            final_summary = _tr(_strip_emoji(source_text[:150]))
        else:
            final_summary = _tr_title(item.get("title", ""))
        items.append({
            "num": f"{i:02d}",
            "title": _strip_emoji(_tr_title(item.get("title", "Untitled"))),
            "url": url,
            "meta": _clean_meta([item.get("author", ""), item.get("time", "")]),
            "summary": final_summary,
            "detail": _strip_emoji(detail_cn) if detail_cn else "",
        })
    sections.append({"title": "深度洞察 (Insights)", "src": "HN Top Blogs + MIT Technology Review", "items": items})

    total_items = sum(len(s["items"]) for s in sections)

    # --- Provenance ---
    prov = intel.get("_provenance", {}).get("starhub", {})
    prov_line = ""
    if prov.get("enabled") and prov.get("snapshot_sources"):
        routed = prov.get("routed", {})
        prov_line = f"StarHub {prov['snapshot_sources']} 源 / {prov['snapshot_items']} 条 → 适配 {prov['adapted_items']} 条 → 路由 " + ", ".join(f"{k}={v}" for k, v in sorted(routed.items()))

    # --- 组装 HTML ---
    generated_time = datetime.now().strftime("%H:%M")
    data_sources = "HN, GitHub, 36Kr, WallStreetCN, V2EX, PH, ArXiv, X, TechCrunch, MIT TR + StarHub (716 RSS)"

    meta_data = {
        "generated_time": generated_time,
        "data_sources": data_sources,
        "total_items": total_items,
        "provenance": prov_line,
    }

    toc_html = _render_toc(sections)
    content_parts = [_render_section(sec, i) for i, sec in enumerate(sections, 1)]
    content_html = ''.join(content_parts)
    meta_html = _render_meta_strip(meta_data)

    title = f"{date_str} 情报日报"
    page = (HTML_TEMPLATE
            .replace('%%TITLE%%', title)
            .replace('%%DATE%%', date_str)
            .replace('%%H1%%', '全球情报日报')
            .replace('%%META%%', meta_html)
            .replace('%%TOCNAV%%', toc_html)
            .replace('%%CONTENT%%', content_html))
    return page


__all__ = ['generate_report']
