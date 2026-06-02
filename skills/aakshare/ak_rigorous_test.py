#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ak_rigorous_test.py — AKShare 核心数据源严谨性基准测试

Frank 指令（2026-06-02 19:10）：研发模式下严谨性测试
  6 个核心接口 (A 股实时行情 / A 股个股财务指标 / A 股个股官方公告 /
  美联储利率 / 美国 CPI / 美国国债收益率)，每接口独立 try-except + 耗时统计
  + DataFrame 结构审计。

生产代码完全不被污染 — 本脚本是孤立 benchmark，输出直接 STDOUT。
"""

import time
import akshare as ak
import pandas as pd


def audit_dataframe(name, df, expected_cols_min=2):
    """严谨审计返回的数据结构"""
    if df is None or df.empty:
        raise ValueError(f"【致命】{name} 接口返回了空数据！")
    print(f"✅ {name} 测试通过 | 数据行数: {len(df)} | 列名预览: {list(df.columns[:5])}")
    print(f"📊 数据切片预览:\n{df.head(2).to_string()}\n" + "-" * 50)


def run_rigorous_test():
    print("🚀 开始执行 AKShare 严谨性基准测试...\n" + "=" * 50)

    # 目标 1: A股实时行情 (以东方财富源为例)
    try:
        start = time.time()
        df = ak.stock_zh_a_spot_em()
        print(f"⏱️ 接口 stock_zh_a_spot_em 耗时: {time.time() - start:.2f}s")
        audit_dataframe("A股实时行情", df)
    except Exception as e:
        print(f"❌ A股实时行情接口崩溃: {e}")

    # 目标 2: 个股深层财务指标 (以贵州茅台 600519 为例)
    try:
        start = time.time()
        df = ak.stock_financial_analysis_indicator(symbol="600519")
        print(f"⏱️ 接口 stock_financial_analysis_indicator 耗时: {time.time() - start:.2f}s")
        audit_dataframe("A股个股财务指标", df)
    except Exception as e:
        print(f"❌ A股财务指标接口崩溃: {e}")

    # 目标 3: 个股最新官方公告列表 (以贵州茅台 600519 为例)
    try:
        start = time.time()
        df = ak.stock_notice_report_em(symbol="600519")
        print(f"⏱️ 接口 stock_notice_report_em 耗时: {time.time() - start:.2f}s")
        audit_dataframe("A股个股官方公告", df)
    except Exception as e:
        print(f"❌ A股官方公告接口崩溃: {e}")

    # 目标 4: 最新美联储利率历史
    try:
        start = time.time()
        df = ak.macro_usa_fed_rate()
        print(f"⏱️ 接口 macro_usa_fed_rate 耗时: {time.time() - start:.2f}s")
        audit_dataframe("美联储利率", df)
    except Exception as e:
        print(f"❌ 美联储利率接口崩溃: {e}")

    # 目标 5: 美国 CPI / PPI 宏观经济指标
    try:
        start = time.time()
        df = ak.macro_usa_cpi()
        print(f"⏱️ 接口 macro_usa_cpi 耗时: {time.time() - start:.2f}s")
        audit_dataframe("美国CPI宏观数据", df)
    except Exception as e:
        print(f"❌ 美国CPI接口崩溃: {e}")

    # 目标 6: 美国国债收益率 (长短期)
    try:
        start = time.time()
        df = ak.macro_usa_treasury_yield()
        print(f"⏱️ 接口 macro_usa_treasury_yield 耗时: {time.time() - start:.2f}s")
        audit_dataframe("美国国债收益率", df)
    except Exception as e:
        print(f"❌ 美国国债收益率接口崩溃: {e}")


if __name__ == "__main__":
    run_rigorous_test()
