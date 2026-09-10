"""Build GitHub Pages: copy generated HTML reports and build index.

数据流:
  cli.py → fetch_all_sources() → generate_report() → HTML 文件 (reports/daily_briefings/)
  build_pages.py → 复制 HTML 到 docs/reports/ + 生成 reports.json 索引
  历史报告持久化：保留 docs/reports/ 中已有的 HTML，合并新报告
"""
import os
import json
import glob
import shutil


def main():
    """复制 HTML 报告到 docs/reports/ 并生成索引（保留历史）。"""
    src_dir = 'reports/daily_briefings'
    dst_dir = 'docs/reports'
    os.makedirs(dst_dir, exist_ok=True)

    # 收集本次 CI 生成的新报告
    new_files = {}
    html_files = glob.glob(os.path.join(src_dir, 'Morning_Report_*.html'))
    for html_path in sorted(html_files, reverse=True):
        fname = os.path.basename(html_path)
        if 'TEST' in fname:
            continue
        date = fname.replace('Morning_Report_', '').replace('.html', '')
        new_files[fname] = {
            'file': fname,
            'title': date + ' 情报日报',
            'date': date,
        }
        dst_path = os.path.join(dst_dir, fname)
        shutil.copy2(html_path, dst_path)
        print(f'Copied: {fname} -> docs/reports/{fname}')

    # 扫描 docs/reports/ 中已有的历史报告（保留未被本次覆盖的）
    existing = glob.glob(os.path.join(dst_dir, 'Morning_Report_*.html'))
    all_reports = dict(new_files)
    for html_path in existing:
        fname = os.path.basename(html_path)
        if fname not in all_reports:
            date = fname.replace('Morning_Report_', '').replace('.html', '')
            all_reports[fname] = {
                'file': fname,
                'title': date + ' 情报日报',
                'date': date,
            }
            print(f'Preserved historical: {fname}')

    # 按日期降序排列
    reports = sorted(all_reports.values(), key=lambda r: r['date'], reverse=True)

    with open('docs/reports.json', 'w', encoding='utf-8') as fp:
        json.dump(reports, fp, ensure_ascii=False)
    print(f'Indexed {len(reports)} reports ({len(new_files)} new + {len(reports) - len(new_files)} historical)')


if __name__ == '__main__':
    main()
