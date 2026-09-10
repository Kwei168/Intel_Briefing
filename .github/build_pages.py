"""Build GitHub Pages: copy generated HTML reports and build index.

简化版：cli.py 已经直接生成 HTML，build_pages.py 只负责：
1. 将 reports/daily_briefings/*.html 复制到 docs/reports/
2. 生成 docs/reports.json 索引文件供首页使用

数据流:
  cli.py → fetch_all_sources() → generate_report() → HTML 文件 (reports/daily_briefings/)
  build_pages.py → 复制 HTML 到 docs/reports/ + 生成 reports.json 索引
"""
import os
import json
import glob
import shutil


def main():
    """复制 HTML 报告到 docs/reports/ 并生成索引。"""
    src_dir = 'reports/daily_briefings'
    dst_dir = 'docs/reports'
    os.makedirs(dst_dir, exist_ok=True)

    html_files = glob.glob(os.path.join(src_dir, 'Morning_Report_*.html'))
    reports = []
    for html_path in sorted(html_files, reverse=True):
        fname = os.path.basename(html_path)
        if 'TEST' in fname:
            continue
        date = fname.replace('Morning_Report_', '').replace('.html', '')
        title = date + ' 情报日报'

        dst_path = os.path.join(dst_dir, fname)
        shutil.copy2(html_path, dst_path)
        reports.append({'file': fname, 'title': title, 'date': date})
        print(f'Copied: {fname} -> docs/reports/{fname}')

    with open('docs/reports.json', 'w', encoding='utf-8') as fp:
        json.dump(reports, fp, ensure_ascii=False)
    print(f'Indexed {len(reports)} reports')


if __name__ == '__main__':
    main()
