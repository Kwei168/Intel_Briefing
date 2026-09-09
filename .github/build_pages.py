"""Build GitHub Pages: convert Markdown reports into StarHub-styled Intel Briefing pages.

彻底重构版（StarHub 设计系统对齐）：
  reports/daily_briefings/Morning_Report_*.md
    -> markdown -> HTML
    -> _enhance() 结构化重排（编辑报头 / 章节目录 / 条目卡片）
    -> docs/reports/*.html + docs/reports.json

结构化规则（与情报日报 Markdown 固定格式对应）:
  # 大标题            -> 报头 mast-title（从正文移除）
  **日期/生成时间/数据源** -> 报头 mast-strip 信息条（从正文移除）
  ## 章节 (English)   -> <section class="intel-section">，H2 带品牌色方块
  > 来源行（章节首引） -> sec-src 来源标签
  ### N. [标题](链接)  -> <div class="intel-card">：编号徽章 + 标题链接
  📡 源 | ⭐ ...      -> ic-meta（mono 元数据行）
  > 💡 摘要           -> ic-summary（品牌色左边框引用）
  📖 阅读原文 / via..  -> ic-foot（卡片底部链接行）
"""
import os, json, glob, re
import markdown

# ══════════════════════════════ HTML 模板（占位符: %%TITLE%% %%DATE%% %%H1%% %%META%% %%TOCNAV%% %%CONTENT%%） ══════════════════════════════

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
/* ════════════ tokens — 对齐 StarHub _build_css() ════════════ */
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

/* ════════════ Header（毛玻璃 + 阅读进度条） ════════════ */
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

/* ════════════ 编辑风格报头 ════════════ */
.mast { max-width:860px; margin:0 auto; padding:26px 20px 0; text-align:center; }
.mast-rule { display:flex; align-items:center; gap:14px; margin:0 0 6px; }
.mast-rule::before,.mast-rule::after { content:""; flex:1; height:1px; background:var(--line-strong); }
.mast-rule span { font-family:var(--mono); font-size:11px; letter-spacing:.14em; color:var(--muted); font-weight:500; white-space:nowrap; }
.mast-title { font-family:var(--display); font-size:clamp(30px,6vw,44px); font-weight:900; letter-spacing:.05em; line-height:1.2; margin:4px 0 10px; }
.mast-strip { display:flex; flex-wrap:wrap; gap:4px 22px; justify-content:center; align-items:baseline; margin-top:6px; padding:9px 14px; border-top:3px double var(--line-strong); border-bottom:1px solid var(--line-strong); }
.ms-item { font-size:12px; color:var(--muted); }
.ms-item b { font-weight:600; color:var(--faint); font-size:10.5px; letter-spacing:.08em; margin-right:6px; }
.ms-item i { font-family:var(--mono); font-style:normal; color:var(--ink); font-size:11.5px; }

/* ════════════ 章节目录（sticky chips） ════════════ */
.toc { position:sticky; top:52px; z-index:30; max-width:860px; margin:14px auto 0; padding:8px 20px; background:rgba(250,249,247,.94); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px); border-bottom:1px solid var(--line); display:flex; align-items:center; gap:10px; }
[data-theme="dark"] .toc { background:rgba(22,20,18,.94); }
.toc-label { flex:none; font-family:var(--mono); font-size:9.5px; font-weight:700; letter-spacing:.12em; color:var(--faint); }
.toc-chips { display:flex; gap:6px; overflow-x:auto; padding-bottom:2px; scrollbar-width:none; }
.toc-chips::-webkit-scrollbar { display:none; }
.toc-chip { flex:none; display:inline-flex; align-items:center; gap:5px; padding:3px 11px; border-radius:999px; border:1px solid var(--line); background:var(--card); font-size:12px; color:var(--muted); transition:all .15s; }
.toc-chip:hover { border-color:var(--brand-line); color:var(--brand-strong); background:var(--brand-weak); }
.toc-chip .n { font-family:var(--mono); font-size:10px; opacity:.75; }

/* ════════════ 正文容器 ════════════ */
.paper { max-width:860px; margin:0 auto; padding:0 20px 56px; }
.article { margin-top:26px; }
.intro { margin:0 0 10px; padding:12px 16px; background:var(--card); border:1px solid var(--line); border-radius:var(--radius); font-size:13.5px; color:var(--muted); line-height:1.8; }
.intro p { margin:0 0 6px; } .intro p:last-child { margin:0; }

/* ════════════ 章节（H2 品牌色方块） ════════════ */
.intel-section { margin:34px 0 0; }
.sec-head { display:flex; align-items:center; gap:12px; padding-bottom:10px; border-bottom:1px solid var(--line); margin-bottom:14px; }
.sec-head h2 { display:flex; align-items:center; gap:10px; font-family:var(--display); font-size:clamp(19px,2.6vw,24px); font-weight:700; line-height:1.3; margin:0; }
.sec-head h2::before { content:""; flex:none; width:10px; height:10px; border-radius:2px; background:var(--brand); }
.sec-count { margin-left:auto; flex:none; font-family:var(--mono); font-size:11px; color:var(--faint); }
.sec-src { display:flex; align-items:center; gap:8px; margin:-4px 0 14px; font-family:var(--mono); font-size:11.5px; color:var(--muted); }
.sec-src .src-label { flex:none; font-size:9.5px; font-weight:700; letter-spacing:.1em; color:var(--brand-strong); background:var(--brand-weak); border:1px solid var(--brand-line); border-radius:4px; padding:1px 6px; }
.sec-quote { margin:0 0 12px; }

/* ════════════ 条目卡片 ════════════ */
.intel-card { background:var(--card); border:1px solid var(--line); border-radius:var(--radius); padding:14px 16px 12px; margin:0 0 12px; transition:box-shadow .18s, border-color .18s, transform .18s; }
.intel-card:hover { border-color:var(--brand-line); box-shadow:var(--shadow-lift); transform:translateY(-2px); }
.ic-head { display:flex; align-items:flex-start; gap:10px; }
.ic-num { flex:none; font-family:var(--mono); font-size:11px; font-weight:700; color:var(--brand-strong); background:var(--brand-weak); border:1px solid var(--brand-line); border-radius:6px; padding:2px 7px; margin-top:2px; }
.ic-head h3 { font-family:var(--display); font-size:15.5px; font-weight:700; line-height:1.5; margin:0; }
.ic-head h3 a { color:var(--ink); transition:color .15s; border-bottom:none; }
.ic-head h3 a:hover { color:var(--brand-strong); }
.ic-meta { display:flex; flex-wrap:wrap; margin:9px 0 0; font-family:var(--mono); font-size:11px; color:var(--faint); line-height:1.6; }
.ic-summary { margin:10px 0 0; padding:9px 14px; background:var(--brand-weak); border-left:3px solid var(--brand); border-radius:0 var(--radius) var(--radius) 0; color:var(--muted); font-size:13px; line-height:1.75; }
.ic-summary p { margin:0; }
.ic-body { margin-top:10px; font-size:13.5px; color:var(--ink); }
.ic-body p { margin:0 0 8px; line-height:1.75; } .ic-body p:last-child { margin:0; }
.ic-foot { display:flex; flex-wrap:wrap; gap:4px 14px; margin-top:10px; padding-top:9px; border-top:1px solid var(--line); font-size:11.5px; color:var(--muted); }
.ic-foot a { color:var(--brand-strong); font-weight:600; border-bottom:none; }
.ic-foot a:hover { text-decoration:underline; text-underline-offset:2px; }

/* ════════════ 正文基础元素（兜底样式） ════════════ */
.article p { margin:0 0 12px; line-height:1.8; font-size:14.5px; }
.article h1 { font-family:var(--display); font-size:clamp(22px,3.5vw,30px); font-weight:900; margin:0 0 16px; line-height:1.3; }
.article h3 { font-family:var(--display); font-size:17px; font-weight:700; margin:22px 0 10px; line-height:1.5; }
.article h4 { font-size:15px; font-weight:700; margin:18px 0 8px; }
.article ul,.article ol { margin:0 0 14px; padding-left:1.5em; }
.article li { margin-bottom:6px; line-height:1.7; }
.article a { color:var(--brand-strong); text-decoration:underline; text-underline-offset:2px; }
.article blockquote { margin:12px 0; padding:10px 16px; background:var(--brand-weak); border-left:3px solid var(--brand); border-radius:0 var(--radius) var(--radius) 0; color:var(--muted); font-size:13.5px; line-height:1.75; }
.article blockquote p { margin:0 0 6px; } .article blockquote p:last-child { margin:0; }
.article code { font-family:var(--mono); font-size:.9em; background:var(--card-2); padding:1px 5px; border-radius:4px; }
.article pre { background:var(--bg); border:1px solid var(--line); border-radius:var(--radius); padding:14px 16px; overflow-x:auto; font-size:12.5px; line-height:1.6; margin:14px 0; }
.article pre code { background:none; padding:0; }
.article table { border-collapse:collapse; width:100%; margin:14px 0; font-size:13.5px; }
.article th,.article td { border:1px solid var(--line); padding:7px 11px; text-align:left; }
.article th { background:var(--card-2); font-weight:600; }
.article img { max-width:100%; height:auto; border-radius:var(--radius); }
.article hr { border:0; border-top:1px solid var(--line); margin:26px 0; }

/* ════════════ 页脚 / 回到顶部 ════════════ */
.foot { margin-top:44px; padding-top:14px; border-top:1px solid var(--line); color:var(--muted); font-size:12px; display:flex; flex-wrap:wrap; gap:6px 18px; justify-content:space-between; }
.foot a { color:var(--brand-strong); font-weight:500; }
.foot a:hover { text-decoration:underline; text-underline-offset:2px; }
.back-top { position:fixed; bottom:24px; right:24px; width:40px; height:40px; border-radius:50%; background:var(--card); border:1px solid var(--line); color:var(--muted); display:flex; align-items:center; justify-content:center; cursor:pointer; opacity:0; pointer-events:none; transition:all .2s; z-index:90; box-shadow:0 2px 8px rgba(0,0,0,.08); }
.back-top.show { opacity:1; pointer-events:auto; }
.back-top:hover { color:var(--brand-strong); border-color:var(--brand-line); background:var(--brand-weak); }
.back-top svg { width:18px; height:18px; }

/* ════════════ Reduced motion ════════════ */
@media (prefers-reduced-motion:reduce) { html { scroll-behavior:auto; } *,*::before,*::after { transition-duration:0s!important; animation-duration:0s!important; } }

/* ════════════ 移动端 700px 断点 ════════════ */
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
  .article p { font-size:14px; }
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
  /* ── 主题（共享 StarHub 存储 key） ── */
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

  /* ── 阅读进度条 + 回到顶部 ── */
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


# ══════════════════════════════ 结构化重排引擎 ══════════════════════════════

BLOCK_TAGS = ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote', 'hr', 'pre', 'ul', 'ol', 'table', 'div')
_TAG_RE = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9]*)')


def _iter_top_blocks(html):
    """按顶层块级标签切分 markdown 生成的 HTML（同名标签配对，嵌套安全）。

    标签边界取真正的 '>'（而非仅标签名末尾），确保切出的块闭合完整。"""
    n = len(html)
    i = 0
    while i < n:
        lt = html.find('<', i)
        if lt == -1:
            return
        m = _TAG_RE.match(html, lt)
        if not m:
            i = lt + 1
            continue
        closing, tag = m.group(1), m.group(2).lower()
        gt = html.find('>', lt)
        if gt == -1:
            return
        tag_end = gt + 1
        if closing or tag not in BLOCK_TAGS:
            i = tag_end
            continue
        if tag == 'hr':
            yield html[lt:tag_end]
            i = tag_end
            continue
        depth, j = 1, tag_end
        while depth > 0 and j < n:
            m2 = _TAG_RE.search(html, j)
            if not m2:
                break
            gt2 = html.find('>', m2.start())
            if gt2 == -1:
                break
            c2, t2 = m2.group(1), m2.group(2).lower()
            if t2 == tag and not c2:
                depth += 1
            elif t2 == tag and c2:
                depth -= 1
            j = gt2 + 1
        yield html[lt:j]
        i = j


def _strip_tags(s):
    """去掉标签并压平 <br>，用于文本特征判断。"""
    s = re.sub(r'<br\s*/?>', ' ', s)
    s = re.sub(r'<[^>]+>', '', s)
    return s.replace('&nbsp;', ' ').strip()


def _inner_of(tag, blk):
    """取块级标签的内部内容（去外壳）。"""
    m = re.match(r'\s*<' + tag + r'(?:\s[^>]*)?>', blk)
    if not m:
        return blk
    end = blk.rfind('</' + tag + '>')
    return blk[m.end():end if end != -1 else len(blk)]


def _clean_head(text):
    """去掉标题前导的 emoji / 符号装饰。"""
    return re.sub(r'^[^\w\u4e00-\u9fff\u3400-\u4dbf(（]+', '', text).strip()


def _rm_headerlink(html):
    return re.sub(r'<a class="headerlink"[^>]*>.*?</a>', '', html, flags=re.S)


def _is_meta_line(txt):
    """条目元数据行：📡 源 | ⭐ 热度 | 🕐 时间。"""
    if not txt or len(txt) > 180:
        return False
    return '📡' in txt or '⭐' in txt or '🕐' in txt or '|' in txt


def _is_foot_line(txt):
    """条目底部链接行：📖 阅读原文 / via ..."""
    if not txt:
        return False
    t = txt.lstrip()
    return '阅读原文' in txt or t.startswith('via') or '📖' in txt


def _parse_meta_items(p_html):
    """报头 meta 段（**标签:** 值 的 <br> 连接块）-> [(label, value)]，过滤日期。"""
    body = _inner_of('p', p_html)
    items = []
    for seg in re.split(r'<br\s*/?>', body):
        m = re.match(r'\s*<strong>(.*?)</strong>\s*:?\s*(.*)$', seg.strip(), flags=re.S)
        if not m:
            continue
        label = _strip_tags(m.group(1)).strip()
        value = _strip_tags(m.group(2)).strip()
        if not label or '日期' in label:
            continue
        items.append((label, value))
    return items


def _linkify(s):
    """把纯文本 URL 转为外链（吞掉句尾中文标点）。"""
    return re.sub(r'(https?://[^\s<>\uff0c\u3002\uff1b\u3001\uff01\uff1f\uff09]+)',
                  r'<a href="\1" target="_blank" rel="noopener">\1</a>', s)


def _split_summary(inner):
    """拆分摘要引用块：markdown 惰性续行会把「阅读原文 / via …」行并入引用块，
    这里把它们拆出来作为卡片底部链接行。返回 (summary_html, foot_html)。"""
    segs = re.split(r'<br\s*/?>', inner)
    keep, foots = [], []
    for seg in segs:
        t = _strip_tags(seg)
        if t and _is_foot_line(t):
            foots.append(seg)
        else:
            keep.append(seg)
    if not foots:
        return inner, ''
    sum_html = '<br>'.join(k for k in keep if _strip_tags(k))
    foot_html = ''.join('<span>%s</span>' % _linkify(f) for f in foots if _strip_tags(f))
    return sum_html, foot_html


def _card_html(c):
    parts = ['<div class="intel-card">']
    num = '<span class="ic-num">%s</span>' % c['num'] if c['num'] else ''
    parts.append('<div class="ic-head">%s<h3>%s</h3></div>' % (num, c['head']))
    if c['meta']:
        parts.append('<div class="ic-meta">%s</div>' % c['meta'])
    if c['summary']:
        sum_html, foot_html = _split_summary(_inner_of('blockquote', c['summary']))
        parts.append('<blockquote class="ic-summary">%s</blockquote>' % sum_html)
        if foot_html and not c['foot']:
            c['foot'] = foot_html
    if c['body']:
        parts.append('<div class="ic-body">%s</div>' % ''.join(c['body']))
    if c['foot']:
        parts.append('<div class="ic-foot">%s</div>' % c['foot'])
    parts.append('</div>')
    return ''.join(parts)


def _section_html(s):
    out = ['<section class="intel-section" id="sec-%d">' % s['num']]
    out.append('<div class="sec-head"><h2>%s</h2><span class="sec-count">%d 条</span></div>'
               % (s['title'], s['count']))
    if s['src']:
        out.append('<div class="sec-src"><span class="src-label">SOURCES</span>%s</div>' % s['src'])
    out.extend(s['blocks'])
    out.append('</section>')
    return ''.join(out)


def _toc_nav(sections):
    if not sections:
        return ''
    chips = ''.join(
        '<a class="toc-chip" href="#sec-%d">%s<span class="n">%d</span></a>'
        % (s['num'], _strip_tags(s['title']), s['count'])
        for s in sections)
    return ('<nav class="toc" aria-label="章节目录"><span class="toc-label">CONTENTS</span>'
            '<div class="toc-chips">%s</div></nav>' % chips)


def _enhance(html, date):
    """把 markdown 渲染结果重组为 报头 + 章节目录 + 条目卡片 结构。

    返回 (h1_text, meta_items, toc_nav_html, content_html, total_items)。
    """
    h1_text = ''
    meta_items = None
    intro = []
    sections = []
    cur_sec = None
    cur_card = None

    def flush_card():
        nonlocal cur_card
        if cur_card is not None and cur_sec is not None:
            cur_sec['blocks'].append(_card_html(cur_card))
        cur_card = None

    for blk in _iter_top_blocks(html):
        m = re.match(r'\s*<([a-zA-Z][a-zA-Z0-9]*)', blk)
        tag = m.group(1).lower() if m else 'raw'

        if tag == 'h1':
            h1_text = _clean_head(_strip_tags(_inner_of('h1', blk)))
            continue
        if tag == 'hr':
            continue
        if tag == 'h2':
            flush_card()
            cur_sec = {'num': len(sections) + 1, 'title': _rm_headerlink(_inner_of('h2', blk)),
                       'src': '', 'count': 0, 'blocks': []}
            sections.append(cur_sec)
            continue
        if tag == 'h3':
            if cur_sec is None:
                cur_sec = {'num': len(sections) + 1, 'title': '本期速览', 'src': '', 'count': 0, 'blocks': []}
                sections.append(cur_sec)
            flush_card()
            inner = _rm_headerlink(_inner_of('h3', blk))
            num_m = re.match(r'^\s*(\d{1,3})\s*[\.、．)）]\s*', _strip_tags(inner))
            num = '{0:02d}'.format(int(num_m.group(1))) if num_m else ''
            head = re.sub(r'^\s*\d{1,3}\s*[\.、．)）]\s*', '', inner)
            cur_card = {'num': num, 'head': head, 'meta': '', 'summary': '', 'body': [], 'foot': ''}
            cur_sec['count'] += 1
            continue
        if tag == 'blockquote':
            if cur_card is not None and not cur_card['summary']:
                cur_card['summary'] = blk
            elif cur_sec is not None and cur_card is None and not cur_sec['src']:
                cur_sec['src'] = _strip_tags(_inner_of('blockquote', blk))
            elif cur_sec is not None:
                cur_sec['blocks'].append('<blockquote class="sec-quote">%s</blockquote>'
                                         % _inner_of('blockquote', blk))
            else:
                intro.append(blk)
            continue
        if tag == 'p':
            txt = _strip_tags(blk)
            if (cur_sec is None and cur_card is None and '<strong>' in blk
                    and ('数据源' in txt or '生成时间' in txt)):
                meta_items = _parse_meta_items(blk)
                continue
            if cur_card is not None:
                if not cur_card['foot'] and _is_foot_line(txt):
                    cur_card['foot'] = _inner_of('p', blk)
                elif not cur_card['meta'] and _is_meta_line(txt):
                    cur_card['meta'] = _inner_of('p', blk)
                else:
                    cur_card['body'].append(blk)
                continue
            if cur_sec is not None:
                cur_sec['blocks'].append(blk)
            else:
                intro.append(blk)
            continue
        # pre / ul / ol / table / div / raw
        if cur_card is not None:
            cur_card['body'].append(blk)
        elif cur_sec is not None:
            cur_sec['blocks'].append(blk)
        else:
            intro.append(blk)
    flush_card()

    chunks = []
    if intro:
        chunks.append('<div class="intro">%s</div>' % ''.join(intro))
    for s in sections:
        chunks.append(_section_html(s))
    content = ''.join(chunks)
    # 站内内容条目均为外链，统一新窗口打开
    content = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', content)

    total = sum(s['count'] for s in sections)
    return h1_text, meta_items, _toc_nav(sections), content, total


# ══════════════════════════════ 构建入口 ══════════════════════════════

def _meta_strip_html(meta_items, date, total):
    spans = []
    for label, value in (meta_items or []):
        spans.append('<span class="ms-item"><b>%s</b><i>%s</i></span>' % (label, value))
    if total:
        spans.append('<span class="ms-item"><b>条目</b><i>%d 条</i></span>' % total)
    if not spans:
        spans.append('<span class="ms-item"><b>日期</b><i>%s</i></span>' % date)
    return ''.join(spans)


def render_page(date, md_content):
    """Render one Markdown report into a UTF-8 HTML page (StarHub design)."""
    html_content = markdown.markdown(
        md_content,
        extensions=['tables', 'fenced_code', 'toc', 'nl2br'],
    )
    try:
        h1, meta_items, toc_html, content_html, total = _enhance(html_content, date)
    except Exception as exc:  # 结构化失败时降级为基础文章样式
        print('  [warn] enhance failed (%s), fallback to raw article' % exc)
        h1, meta_items, toc_html, content_html, total = '', None, '', html_content, 0
    if not h1:
        h1 = date + ' 情报日报'
    page = (HTML_TEMPLATE
            .replace('%%TITLE%%', date + ' 情报日报')
            .replace('%%DATE%%', date)
            .replace('%%H1%%', h1)
            .replace('%%META%%', _meta_strip_html(meta_items, date, total))
            .replace('%%TOCNAV%%', toc_html)
            .replace('%%CONTENT%%', content_html))
    return page


def main():
    md_files = glob.glob('reports/daily_briefings/Morning_Report_*.md')
    reports = []
    for md_path in sorted(md_files, reverse=True):
        fname = os.path.basename(md_path)
        if 'TEST' in fname:
            continue
        date = fname.replace('Morning_Report_', '').replace('.md', '')
        html_name = fname.replace('.md', '.html')
        title = date + ' 情报日报'
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        full_html = render_page(date, md_content)
        out_path = os.path.join('docs/reports', html_name)
        os.makedirs('docs/reports', exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(full_html)
        reports.append({'file': html_name, 'title': title, 'date': date})
        print(f'Converted: {fname} -> {html_name}')
    with open('docs/reports.json', 'w', encoding='utf-8') as fp:
        json.dump(reports, fp, ensure_ascii=False)
    print(f'Indexed {len(reports)} reports')


if __name__ == '__main__':
    main()
