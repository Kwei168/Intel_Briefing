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
:root{{--bg:#faf9f7;--card:#fffdf9;--card-2:#f3efe6;--border:#ddd6c9;--border2:#eae4d8;--text:#1c1917;--muted:#5f594c;--faint:#746d60;--brand:#2f5d8a;--brand-strong:#24496e;--brand-line:#b9cde0;--brand-weak:#e7eef4;--accent:var(--brand);--accent-line:var(--brand-line);--accent-weak:var(--brand-weak);--accent-solid:#2f5d8a;--on-strong:#fdfcf9;--hover:#f2efe8;--hover-line:#b3ab9b;--line:#e4ddd0;--line-strong:#b9b0a2;--display:'Noto Serif SC','Songti SC','STSong','SimSun',serif;--body:'Noto Sans SC','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;--mono:'IBM Plex Mono','SFMono-Regular',Consolas,'Liberation Mono',monospace;--radius:4px}}
[data-theme=dark]{{--bg:#161412;--card:#1d1a17;--card-2:#221f1a;--border:#37312a;--border2:#2b2621;--text:#ece7df;--muted:#a59d90;--faint:#8a8275;--brand:#8fb3d9;--brand-strong:#b0cbe6;--brand-line:#3d5a78;--brand-weak:#22303f;--accent:var(--brand);--accent-line:var(--brand-line);--accent-weak:var(--brand-weak);--accent-solid:#9db8d4;--on-strong:#16181d;--hover:#242019;--hover-line:#4a4339;--line:#2a2d33;--line-strong:#4a4e57}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--body);background:var(--bg);color:var(--text);line-height:1.65;font-size:15px;-webkit-font-smoothing:antialiased}}
a{{color:inherit;text-decoration:none}}
::selection{{background:var(--brand-weak);color:var(--text)}}
.paper{{max-width:980px;margin:0 auto;padding:0 20px 64px}}
.topbar{{display:flex;align-items:center;gap:10px;padding:14px 0 4px}}
.back{{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:999px;background:var(--card);border:1px solid var(--border);font-size:13px;transition:all .15s;color:var(--text)}}
.back:hover{{border-color:var(--accent);color:var(--brand-strong)}}
.topbar .spacer{{flex:1}}
.theme-btn{{width:36px;height:36px;border-radius:999px;background:var(--card);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--text);transition:all .15s}}
.theme-btn:hover{{border-color:var(--accent)}}
.theme-btn svg{{width:16px;height:16px}}
.icon-moon{{display:none}}
[data-theme=dark] .icon-sun{{display:none}}
[data-theme=dark] .icon-moon{{display:block}}
.masthead{{text-align:center;padding:26px 0 0}}
.mast-rule{{display:flex;align-items:center;gap:14px;margin:0 0 4px}}
.mast-rule::before,.mast-rule::after{{content:"";flex:1;height:1px;background:var(--line-strong)}}
.mast-meta{{font-size:11.5px;letter-spacing:.14em;color:var(--muted);font-weight:500;white-space:nowrap}}
.mast-title{{font-family:var(--display);font-size:clamp(28px,5vw,42px);font-weight:900;letter-spacing:.06em;line-height:1.15;margin:6px 0 2px}}
.mast-sub{{font-size:12.5px;color:var(--muted);letter-spacing:.1em}}
.article{{margin-top:32px}}
.article h1{{font-family:var(--display);font-size:clamp(24px,4vw,32px);font-weight:900;margin:0 0 16px;line-height:1.3;border-bottom:3px double var(--line-strong);padding-bottom:12px}}
.article h2{{font-family:var(--display);font-size:clamp(20px,3vw,26px);font-weight:700;margin:32px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}}
.article h3{{font-family:var(--display);font-size:18px;font-weight:700;margin:24px 0 8px}}
.article h4{{font-size:15px;font-weight:700;margin:20px 0 6px}}
.article p{{margin:0 0 12px;line-height:1.75}}
.article ul,.article ol{{margin:0 0 12px;padding-left:24px}}
.article li{{margin-bottom:6px;line-height:1.7}}
.article a{{color:var(--brand-strong);border-bottom:1px solid var(--brand-line);transition:all .15s}}
.article a:hover{{border-bottom-color:var(--brand-strong)}}
.article blockquote{{margin:16px 0;padding:12px 20px;background:var(--card-2);border-left:4px solid var(--accent);border-radius:0 4px 4px 0;color:var(--muted)}}
.article code{{font-family:var(--mono);font-size:13px;background:var(--card-2);padding:2px 6px;border-radius:3px}}
.article pre{{background:var(--card-2);padding:16px;border-radius:4px;overflow-x:auto;margin:16px 0;border:1px solid var(--border)}}
.article pre code{{background:transparent;padding:0}}
.article table{{width:100%;border-collapse:collapse;margin:16px 0;font-size:14px}}
.article th,.article td{{padding:10px 14px;border:1px solid var(--border);text-align:left}}
.article th{{background:var(--card-2);font-weight:700;font-size:13px}}
.article img{{max-width:100%;height:auto;border-radius:4px}}
.article hr{{border:0;border-top:1px solid var(--line);margin:28px 0}}
.foot{{margin-top:48px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px;display:flex;flex-wrap:wrap;gap:6px 18px;justify-content:space-between}}
.foot a{{color:var(--brand-strong);font-weight:500}}
.foot a:hover{{text-decoration:underline}}
@media (max-width:760px){{.paper{{padding:0 14px 48px}}.mast-title{{letter-spacing:.03em}}}}
</style>
<script>try{{var _t=localStorage.getItem('wb_starhub_theme_v1')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');document.documentElement.dataset.theme=_t}}catch(e){{}}</script>
</head>
<body>
<div class="paper">
  <div class="topbar">
    <a class="back" href="../index.html" title="日报列表">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg>
      日报列表
    </a>
    <div class="spacer"></div>
    <button class="theme-btn" id="btnTheme" title="切换明暗主题" aria-label="切换明暗主题">
      <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5.3 5.3l1.7 1.7M17 17l1.7 1.7M18.7 5.3 17 7M7 17l-1.7 1.7"/></svg>
      <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z"/></svg>
    </button>
  </div>
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
    <span><a href="../index.html">返回首页</a> &middot; <a href="https://kwei168.github.io/StarHub/">StarHub</a></span>
  </footer>
</div>
<script>
var btn=document.getElementById('btnTheme');
if(btn)btn.onclick=function(){{var t=document.documentElement.dataset.theme==='dark'?'light':'dark';try{{localStorage.setItem('wb_starhub_theme_v1',t)}}catch(e){{}}document.documentElement.dataset.theme=t}};
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