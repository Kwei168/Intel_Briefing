"""Build GitHub Pages: convert Markdown reports to StarHub-styled HTML."""
import os, json, glob
import markdown

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title} - Intel Briefing</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@700;900&family=Noto+Sans+SC:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
/* ══════════════ tokens (StarHub Editorial Data-Book) ══════════════ */
:root{{
  --bg:#faf9f7;--card:#fffdf9;--card-2:#f3efe6;--card-3:#ebe6db;
  --ink:#1c1917;--muted:#5f594c;--faint:#6e685e;
  --line:#ddd6c9;--line-strong:#b9b0a2;
  --brand:#2f5d8a;--brand-strong:#24496e;--brand-line:#b9cde0;--brand-weak:#e7eef4;
  --display:"Noto Serif SC","Georgia","Times New Roman","Songti SC","SimSun","STSong",serif;
  --body:"Noto Sans SC",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  --mono:"IBM Plex Mono","SF Mono","Fira Code","Consolas",monospace;
  --radius:8px;
  --shadow:0 1px 2px rgba(28,25,23,.05);
  --shadow-lift:0 10px 26px rgba(0,0,0,.10),0 2px 4px rgba(0,0,0,.06);
}}
[data-theme="dark"]{{
  --bg:#161412;--card:#1d1a17;--card-2:#262019;--card-3:#2f2820;
  --ink:#ece7df;--muted:#a59d90;--faint:#a8a090;
  --line:#37312a;--line-strong:#4a4339;
  --brand:#8fb3d9;--brand-strong:#b0cbe6;--brand-line:#3d5a78;--brand-weak:#22303f;
  --shadow:0 1px 2px rgba(0,0,0,.4);
  --shadow-lift:0 10px 26px rgba(0,0,0,.5),0 2px 4px rgba(0,0,0,.4);
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
html{{scroll-behavior:smooth;}}
body{{font-family:var(--body);background:var(--bg);color:var(--ink);line-height:1.55;font-size:14px;-webkit-font-smoothing:antialiased;}}
a{{color:inherit;text-decoration:none;}}
button{{font-family:inherit;cursor:pointer;border:none;background:none;color:inherit;}}
:focus-visible{{outline:2px solid var(--brand);outline-offset:2px;border-radius:var(--radius);}}
::selection{{background:var(--brand-weak);color:var(--ink);}}

/* ══════════════ Header (glassmorphism) ══════════════ */
header{{position:sticky;top:0;z-index:40;background:rgba(250,249,247,.94);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);}}
[data-theme="dark"] header{{background:rgba(22,20,18,.94);}}
.hd{{max-width:860px;margin:0 auto;padding:9px 20px;display:flex;align-items:center;gap:12px;}}
.hd .logo{{display:flex;align-items:center;gap:8px;flex:none;font-family:var(--display);font-weight:900;font-size:16px;}}
.hd .logo .sub{{font-size:11px;color:var(--muted);font-weight:400;margin-left:2px;font-family:var(--body);}}
.hd .nav-links{{display:flex;align-items:center;gap:2px;flex:1;}}
.hd .nav-links a{{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;padding:5px 12px;border-radius:999px;font-size:12.5px;font-weight:500;border:1px solid transparent;transition:all .15s;}}
.hd .nav-links a:hover{{background:var(--card);border-color:var(--line);}}
.hd .nav-links a.active{{background:var(--brand-weak);border-color:var(--brand-line);color:var(--brand-strong);font-weight:600;}}
.theme-btn{{width:30px;height:30px;border-radius:999px;background:var(--card);border:1px solid var(--line);display:flex;align-items:center;justify-content:center;flex:none;transition:all .15s;}}
.theme-btn:hover{{border-color:var(--brand-line);}}
.theme-btn svg{{width:14px;height:14px;}}
.icon-moon{{display:none;}}
[data-theme="dark"] .icon-sun{{display:none;}}
[data-theme="dark"] .icon-moon{{display:block;}}

/* ══════════════ Masthead ═════════════ */
.masthead{{text-align:center;padding:28px 0 0;}}
.mast-rule{{display:flex;align-items:center;gap:14px;margin:0 0 4px;}}
.mast-rule::before,.mast-rule::after{{content:"";flex:1;height:1px;background:var(--line-strong);}}
.mast-meta{{font-size:11.5px;letter-spacing:.14em;color:var(--muted);font-weight:500;white-space:nowrap;}}
.mast-title{{font-family:var(--display);font-size:clamp(26px,4.5vw,38px);font-weight:900;letter-spacing:.06em;line-height:1.15;margin:6px 0 2px;}}
.mast-sub{{font-size:12.5px;color:var(--muted);letter-spacing:.1em;}}

/* ══════════════ Article ══════════════ */
.article-wrap{{max-width:860px;margin:0 auto;padding:0 20px 64px;}}
.article{{margin-top:28px;}}

/* Article title */
.article h1{{font-family:var(--display);font-size:clamp(22px,3.5vw,30px);font-weight:900;margin:0 0 20px;line-height:1.3;color:var(--ink);}}

/* Meta info card */
.article .meta-card{{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 20px;margin-bottom:32px;}}
.article .meta-card dl{{display:grid;grid-template-columns:auto 1fr;gap:8px 16px;margin:0;font-size:14px;}}
.article .meta-card dt{{color:var(--muted);font-weight:500;white-space:nowrap;}}
.article .meta-card dd{{color:var(--ink);margin:0;line-height:1.6;}}
.article .meta-card dd a{{color:var(--brand-strong);border-bottom:1px solid var(--brand-line);}}
.article .meta-card dd a:hover{{border-bottom-color:var(--brand-strong);}}

/* Section headings */
.article h2{{font-family:var(--display);font-size:clamp(18px,2.8vw,24px);font-weight:700;margin:36px 0 16px;padding-bottom:10px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px;color:var(--ink);}}
.article h2 .sec-icon{{width:8px;height:8px;border-radius:2px;background:var(--brand);flex:none;}}
.article h3{{font-family:var(--display);font-size:17px;font-weight:700;margin:24px 0 10px;color:var(--ink);}}
.article h4{{font-size:15px;font-weight:700;margin:20px 0 8px;color:var(--ink);}}

/* Paragraphs */
.article p{{margin:0 0 14px;line-height:1.75;font-size:15px;color:var(--ink);}}

/* Lists */
.article ul,.article ol{{margin:0 0 16px;padding-left:24px;}}
.article li{{margin-bottom:8px;line-height:1.7;font-size:14.5px;color:var(--ink);}}

/* Links */
.article a{{color:var(--brand-strong);border-bottom:1px solid var(--brand-line);transition:all .15s;}}
.article a:hover{{border-bottom-color:var(--brand-strong);}}

/* Blockquotes - source attribution */
.article blockquote{{margin:16px 0;padding:14px 20px;background:var(--card-2);border-left:4px solid var(--brand);border-radius:0 var(--radius) var(--radius) 0;color:var(--muted);font-size:14px;line-height:1.7;}}
.article blockquote p{{margin:0 0 8px;color:var(--muted);}}
.article blockquote p:last-child{{margin-bottom:0;}}
.article blockquote a{{color:var(--brand-strong);font-weight:500;}}

/* Source chips */
.article .source-chip{{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;background:var(--brand-weak);border:1px solid var(--brand-line);border-radius:4px;font-size:12px;color:var(--brand-strong);font-weight:500;margin-right:6px;margin-bottom:4px;}}
.article .source-chip .chip-icon{{font-size:10px;opacity:.7;}}

/* Code */
.article code{{font-family:var(--mono);font-size:13px;background:var(--card-2);padding:2px 6px;border-radius:4px;color:var(--ink);}}
.article pre{{background:var(--card-2);padding:16px;border-radius:var(--radius);overflow-x:auto;margin:16px 0;border:1px solid var(--line);}}
.article pre code{{background:transparent;padding:0;font-size:13px;}}

/* Tables */
.article table{{width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;}}
.article th,.article td{{padding:10px 14px;border:1px solid var(--line);text-align:left;}}
.article th{{background:var(--card-2);font-weight:700;font-size:13px;color:var(--ink);}}
.article td{{color:var(--ink);}}

/* Images */
.article img{{max-width:100%;height:auto;border-radius:var(--radius);margin:16px 0;}}

/* Horizontal rule */
.article hr{{border:0;border-top:1px solid var(--line);margin:32px 0;}}

/* Card-style numbered items */
.article .item-card{{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 20px;margin-bottom:16px;transition:border-color .15s,box-shadow .15s;}}
.article .item-card:hover{{border-color:var(--brand-line);box-shadow:var(--shadow);}}
.article .item-card h3{{margin:0 0 10px;font-size:16px;font-weight:700;line-height:1.5;}}
.article .item-card h3 a{{color:var(--ink);border-bottom:none;}}
.article .item-card h3 a:hover{{color:var(--brand-strong);}}
.article .item-card .item-meta{{display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:12.5px;color:var(--muted);margin-top:10px;padding-top:10px;border-top:1px solid var(--line);}}
.article .item-card .item-meta .chip{{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;background:var(--card-2);border-radius:4px;font-size:11.5px;color:var(--faint);}}
.article .item-card .item-meta .chip.brand{{background:var(--brand-weak);color:var(--brand-strong);}}
.article .item-card p{{margin:10px 0 0;font-size:14px;color:var(--muted);line-height:1.7;}}

/* ═════════════ Footer ══════════════ */
.foot{{margin-top:48px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px;display:flex;flex-wrap:wrap;gap:6px 18px;justify-content:space-between;}}
.foot a{{color:var(--brand-strong);font-weight:500;}}
.foot a:hover{{text-decoration:underline;}}

/* ══════════════ Back to top ══════════════ */
.back-top{{position:fixed;bottom:24px;right:24px;width:40px;height:40px;border-radius:50%;background:var(--card);border:1px solid var(--line);color:var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer;opacity:0;pointer-events:none;transition:all .2s;z-index:90;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
.back-top.show{{opacity:1;pointer-events:auto;}}
.back-top:hover{{color:var(--brand-strong);border-color:var(--brand-line);background:var(--brand-weak);}}
.back-top svg{{width:18px;height:18px;}}

/* ══════════════ Reduced motion ══════════════ */
@media (prefers-reduced-motion:reduce){{*,*::before,*::after{{transition-duration:0s!important;animation-duration:0s!important;}}}}

/* ══════════════ Responsive ══════════════ */
@media (max-width:900px){{
  .hd .logo .sub{{display:none;}}
  .article-wrap{{padding:0 14px 48px;}}
}}
@media (max-width:700px){{
  .hd .nav-links a{{padding:5px 9px;font-size:12px;}}
  .mast-title{{letter-spacing:.03em;}}
  .article h1{{font-size:20px;}}
  .article h2{{font-size:18px;}}
  .article p{{font-size:14px;}}
  .article .item-card{{padding:14px 16px;}}
  .article .item-card h3{{font-size:15px;}}
  .article .meta-card{{padding:14px 16px;}}
  .article .meta-card dl{{font-size:13px;}}
}}
</style>
<script>try{{var _t=localStorage.getItem('wb_starhub_theme_v1')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');document.documentElement.dataset.theme=_t}}catch(e){{}}</script>
</head>
<body>

<!-- ── Header ── -->
<header>
  <div class="hd">
    <div class="logo">
      <a href="../index.html" style="color:inherit;display:inline-flex;align-items:center;gap:8px;">
        <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg>
        日报列表
      </a>
      <span class="sub">{date}</span>
    </div>
    <div class="nav-links">
      <a href="https://kwei168.github.io/StarHub/">🏠 首页</a>
      <a href="https://kwei168.github.io/StarHub/rss-aggregator.html"> RSS</a>
      <a href="https://kwei168.github.io/StarHub/ai-daily.html">📰 AI 晨报</a>
      <a href="../index.html" class="active">📋 日报</a>
    </div>
    <button class="theme-btn" id="btnTheme" title="切换明暗主题" aria-label="切换明暗主题">
      <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5.3 5.3l1.7 1.7M17 17l1.7 1.7M18.7 5.3 17 7M7 17l-1.7 1.7"/></svg>
      <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z"/></svg>
    </button>
  </div>
</header>

<!-- ── Masthead ── -->
<div class="article-wrap">
  <header class="masthead">
    <div class="mast-rule"><span class="mast-meta">{date}</span><span class="mast-meta">INTEL BRIEFING</span></div>
    <h1 class="mast-title">Intel Briefing</h1>
    <div class="mast-sub">UNIFIED INTELLIGENCE ENGINE &middot; 每日情报日报</div>
  </header>

  <article class="article">
{content}
  </article>

  <footer class="foot">
    <span>由 <a href="https://github.com/Kwei168/Intel_Briefing" target="_blank" rel="noopener">Intel_Briefing</a> 引擎自动生成</span>
    <span>{date} &middot; 内容版权归原作者所有</span>
    <span><a href="../index.html">← 返回列表</a> &middot; <a href="https://kwei168.github.io/StarHub/">StarHub</a></span>
  </footer>
</div>

<!-- ── Back to top ── -->
<button class="back-top" id="backTop" title="回到顶部" aria-label="回到顶部">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 15l-6-6-6 6"/></svg>
</button>

<script>
/* Theme toggle */
var btn=document.getElementById('btnTheme');
if(btn)btn.onclick=function(){{var t=document.documentElement.dataset.theme==='dark'?'light':'dark';try{{localStorage.setItem('wb_starhub_theme_v1',t)}}catch(e){{}}document.documentElement.dataset.theme=t}};

/* Back to top */
var bt=document.getElementById('backTop');
window.addEventListener('scroll',function(){{bt.classList.toggle('show',window.scrollY>400);}},{{passive:true}});
bt.onclick=function(){{window.scrollTo({{top:0,behavior:'smooth'}});}};

/* Keyboard: T=theme, ArrowUp=top */
document.addEventListener('keydown',function(e){{
  var tag=e.target.tagName;
  if(tag==='INPUT'||tag==='TEXTAREA')return;
  if(e.key==='t'||e.key==='T'){{btn.click();}}
  else if(e.key==='ArrowUp'&&window.scrollY<10){{window.scrollTo({{top:0,behavior:'smooth'}});}}
}});
</script>
</body>
</html>"""


def render_page(date, md_content):
    """Render one Markdown report into a UTF-8 HTML page."""
    html_content = markdown.markdown(
        md_content,
        extensions=['tables', 'fenced_code', 'toc', 'nl2br'],
    )
    title = date + ' 情报日报'
    return HTML_TEMPLATE.format(title=title, date=date, content=html_content)


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
