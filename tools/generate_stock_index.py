#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_stock_index.py - 沪深京全量 A 股代码与简称映射生成器

【用途】
- 抓取当前 (沪深京) 三市全部 A 股的代码 + 简称
- 输出到 public/data/stock_index.json, 供 api/dividend.py 真实检索
- 一次抓取后所有静态托管, 后续 api 调用零网络依赖

【数据源】
- akshare.stock_zh_a_spot_em() (东方财富接口, 含沪深京)
- 单次抓取 ~5000+ 只, 耗时 5-15s, 每日 1 次足够

【输出 schema】
[
  {"code": "600519", "name": "贵州茅台"},
  ...
]
"""
import akshare as ak
import json
import os
import sys
import time
from pathlib import Path


def generate():
    """抓取全量 A 股实时行情快照, 提取代码 + 名称

    优先用 stock_zh_a_spot (新浪, 含北交所 bj920xxx, 5526 行, ~14s)
    Fallback: stock_info_a_code_name (上交所/深交所基础表, 5527 行, ~11s, 不含北交所)
    """
    df = None
    src = None
    print("[generate] 尝试 stock_zh_a_spot (新浪, 含北交所)...")
    t0 = time.time()
    try:
        df = ak.stock_zh_a_spot()
        src = 'stock_zh_a_spot (新浪, 含北交所)'
    except Exception as e:
        print(f"[generate] 新浪接口失败: {type(e).__name__}: {e}", file=sys.stderr)
        print("[generate] 尝试 fallback: stock_info_a_code_name...")
        try:
            df = ak.stock_info_a_code_name()
            src = 'stock_info_a_code_name (深交所/上交所基础表, 不含北交所)'
        except Exception as e2:
            print(f"[generate] fallback 也失败: {type(e2).__name__}: {e2}", file=sys.stderr)
            return 1

    elapsed = time.time() - t0
    print(f"[generate] 抓取完成: {len(df)} 行, 耗时 {elapsed:.1f}s ({src})")

    # 适配两种接口的列名
    code_col = '代码' if '代码' in df.columns else 'code'
    name_col = '名称' if '名称' in df.columns else 'name'
    if code_col not in df.columns or name_col not in df.columns:
        print(f"[generate] ❌ 缺列 code/name, 实际列: {list(df.columns)}", file=sys.stderr)
        return 1

    # 提取代码和名称
    stock_list = []
    seen_codes = set()
    for _, row in df.iterrows():
        code = str(row[code_col]).strip()
        name = str(row[name_col]).strip()
        if not code or not name:
            continue
        # 接受 6 位数字 (沪深主板/创业板/科创板) 或 bj+6 位 (北交所)
        if code in seen_codes:
            continue
        seen_codes.add(code)
        stock_list.append({"code": code, "name": name})

    # 排序: 按代码升序
    stock_list.sort(key=lambda x: x['code'])

    output_path = Path.home() / ".openclaw" / "workspace-jobs" / "public" / "data" / "stock_index.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(stock_list, f, ensure_ascii=False, indent=2)

    # 统计各市场
    sh_main = sum(1 for s in stock_list if s['code'].startswith('60'))
    sh_kechuang = sum(1 for s in stock_list if s['code'].startswith('688'))
    sz_main = sum(1 for s in stock_list if s['code'].startswith('00'))
    sz_chuangye = sum(1 for s in stock_list if s['code'].startswith('30'))
    bj = sum(1 for s in stock_list if s['code'].startswith('bj'))
    other = len(stock_list) - sh_main - sh_kechuang - sz_main - sz_chuangye - bj

    print(f"[generate] ✅ 成功导出 {len(stock_list)} 只股票至 {output_path}")
    print(f"[generate]   沪市主板 (60xxxx): {sh_main}")
    print(f"[generate]   沪市科创 (688xxx): {sh_kechuang}")
    print(f"[generate]   深市主板 (00xxxx): {sz_main}")
    print(f"[generate]   深市创业 (30xxxx): {sz_chuangye}")
    print(f"[generate]   北交所 (bjxxxxx): {bj}")
    print(f"[generate]   其它: {other}")
    print(f"[generate] 前 3 只: {stock_list[:3]}")
    print(f"[generate] 后 3 只: {stock_list[-3:]}")
    return 0


if __name__ == '__main__':
    sys.exit(generate())
