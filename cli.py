#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intel Briefing CLI - 命令行入口
Unified Intelligence Fetcher V2

generate_report() 直接返回完整 HTML 字符串，
cli.py 直接保存为 .html 文件。不再有 Markdown 或 JSON 中间层。
"""

import sys
import os
import argparse
from datetime import datetime

from src.intel_collector import fetch_all_sources
from src.report_generator import generate_report


def main():
    parser = argparse.ArgumentParser(description="Unified Intelligence Fetcher V2")
    parser.add_argument("--limit", type=int, default=10, help="Items per source")
    parser.add_argument("--test", action="store_true", help="Test mode (1 item per source)")
    parser.add_argument("--output", type=str, help="Custom output path")
    args = parser.parse_args()
    
    limit = 1 if args.test else args.limit
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    print(f"\n{'='*50}")
    print(f"  Unified Intelligence Fetcher V2")
    print(f"  Date: {date_str} | Limit: {limit}/source")
    _sh_status = ""
    try:
        from src.config import STARHUB_BRIDGE_ENABLED
        _sh_status = " + StarHub(716 RSS)" if STARHUB_BRIDGE_ENABLED else " (StarHub disabled)"
    except ImportError:
        pass
    print(f"  Sources: HN, GitHub, 36Kr, WS, V2EX, PH, ArXiv, X, TC, MIT-TR{_sh_status}")
    try:
        from src.config import cfg
        print("  Credentials: XAI=%s | Gemini=%s | ProductHunt=%s" % (
            "SET" if cfg.xai_api_key else "UNSET",
            "SET" if cfg.gemini_api_key else "UNSET",
            "SET" if cfg.producthunt_token else "UNSET",
        ))
    except (ImportError, AttributeError):
        print("  Credentials: unavailable")
    print(f"{'='*50}\n")
    
    # Fetch
    intel = fetch_all_sources(limit_per_source=limit)
    
    # Generate HTML directly (no intermediate format)
    html_content = generate_report(intel, date_str)
    
    # Save as .html
    if args.output:
        output_path = args.output
    else:
        reports_dir = os.path.join(os.path.dirname(__file__), "reports", "daily_briefings")
        os.makedirs(reports_dir, exist_ok=True)
        if args.test:
            output_path = os.path.join(reports_dir, "Morning_Report_TEST.html")
        else:
            output_path = os.path.join(reports_dir, f"Morning_Report_{date_str}.html")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"\n[SUCCESS] HTML report saved to: {output_path}")


if __name__ == "__main__":
    main()
