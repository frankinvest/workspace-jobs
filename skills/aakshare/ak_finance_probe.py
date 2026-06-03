#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ak_finance_probe.py — 茅台 (600519) 财务指标单步探测 (v1)

Frank 2026-06-03 16:35 指令:
  探测 stock_financial_abstract_onvanya 和 stock_financial_analysis_indicator_intel_em

⚠️ 重要修正 (透明汇报):
  - `stock_financial_abstract_onvanya`           — 不存在 (拼写错)
  - `stock_financial_analysis_indicator_intel_em` — 不存在 (拼写错)
  - 真实接口: `stock_financial_analysis_indicator_em` (东财)

本脚本探测 5 个备选接口 (含 Frank 提到的 2 个 + 3 个其他可能), 找出能拿到
茅台 (600519) 财务净利润的方案。

执行: python3 skills/aakshare/ak_finance_probe.py
"""
import time
import pandas as pd
import akshare as ak


def try_call(name, fn, *args, **kwargs):
    """统一 try-except 包装 + 耗时统计"""
    start = time.time()
    try:
        df = fn(*args, **kwargs)
        elapsed = time.time() - start
        return ("OK", df, elapsed, None)
    except Exception as e:
        elapsed = time.time() - start
        return ("ERR", None, elapsed, f"{type(e).__name__}: {str(e)[:200]}")


def find_net_profit_columns(df, max_show=5):
    """找包含'净利'的列, 展示每列前几行"""
    if df is None or df.empty:
        return []
    found = []
    for col in df.columns:
        col_str = str(col)
        if "净利" in col_str or "净利润" in col_str:
            found.append(col)
    return found[:max_show]


def show(df, name, n=3):
    """统一展示"""
    print(f"  rows={len(df)}, cols={list(df.columns)}")
    print(df.head(n).to_string(max_cols=8))
    print()


def main():
    print("=" * 70)
    print("🔍 茅台 (600519) 财务指标单步探测 v1")
    print("=" * 70)
    print(f"📌 akshare v{ak.__version__}")
    print()

    # ─────────────────────────────────────────────────────────
    # 探测 1: Frank 原名 (已知空数据)
    # ─────────────────────────────────────────────────────────
    print("\n【探测 1: stock_financial_analysis_indicator('600519') — Frank 原名, 已知空】")
    status, df, elapsed, err = try_call(
        "1) stock_financial_analysis_indicator(600519)",
        ak.stock_financial_analysis_indicator, symbol="600519"
    )
    print(f"  status: {status} | elapsed: {elapsed:.2f}s")
    if err:
        print(f"  err: {err}")
    if status == "OK" and df is not None:
        show(df, "1)")
        net_cols = find_net_profit_columns(df)
        print(f"  🔎 含'净利'的列: {net_cols}")

    # ─────────────────────────────────────────────────────────
    # 探测 2: Frank 提到的备选 1 (东财 intel_em → 实际是 _em)
    # ─────────────────────────────────────────────────────────
    print("\n【探测 2: stock_financial_analysis_indicator_em — 东财 intel (Frank 备选 1)】")
    # 注意: ak 接口签名是 stock_financial_analysis_indicator_em(symbol='301389.SZ', indicator='按报告期')
    # 茅台 600519 是上交所, 用 600519 (ak 内部会处理)
    status, df, elapsed, err = try_call(
        "2) stock_financial_analysis_indicator_em(600519, 按报告期)",
        ak.stock_financial_analysis_indicator_em, symbol="600519", indicator="按报告期"
    )
    print(f"  status: {status} | elapsed: {elapsed:.2f}s")
    if err:
        print(f"  err: {err}")
    if status == "OK" and df is not None:
        show(df, "2)")
        net_cols = find_net_profit_columns(df)
        print(f"  🔎 含'净利'的列: {net_cols}")
        if net_cols:
            # 提取净利润列前 5 行
            print(f"\n  📌 净利润数据 (前 5 期):")
            for col in net_cols[:3]:
                print(f"     {col}: {df[col].head(5).tolist()}")

    # ─────────────────────────────────────────────────────────
    # 探测 3: Frank 提到的备选 2 (abstract_onvanya → 实际是 abstract)
    # ─────────────────────────────────────────────────────────
    print("\n【探测 3: stock_financial_abstract('600519') — abstract (Frank 备选 2)】")
    status, df, elapsed, err = try_call(
        "3) stock_financial_abstract(600519)",
        ak.stock_financial_abstract, symbol="600519"
    )
    print(f"  status: {status} | elapsed: {elapsed:.2f}s")
    if err:
        print(f"  err: {err}")
    if status == "OK" and df is not None:
        show(df, "3)")
        net_cols = find_net_profit_columns(df)
        print(f"  🔎 含'净利'的列: {net_cols}")

    # ─────────────────────────────────────────────────────────
    # 探测 4: 新浪源 (备选 3, 备查)
    # ─────────────────────────────────────────────────────────
    print("\n【探测 4: stock_financial_report_sina('sh600519', '利润表') — 新浪源】")
    status, df, elapsed, err = try_call(
        "4) stock_financial_report_sina(sh600519, 利润表)",
        ak.stock_financial_report_sina, stock="sh600519", symbol="利润表"
    )
    print(f"  status: {status} | elapsed: {elapsed:.2f}s")
    if err:
        print(f"  err: {err}")
    if status == "OK" and df is not None:
        show(df, "4)")
        net_cols = find_net_profit_columns(df)
        print(f"  🔎 含'净利'的列: {net_cols}")

    # ─────────────────────────────────────────────────────────
    # 探测 5: 同花顺摘要 (备选 4, 备查)
    # ─────────────────────────────────────────────────────────
    print("\n【探测 5: stock_financial_abstract_ths — 同花顺摘要】")
    # ths 接口可能需要不同参数, 先 try 最小调用
    status, df, elapsed, err = try_call(
        "5) stock_financial_abstract_ths",
        ak.stock_financial_abstract_ths, symbol="600519"
    )
    print(f"  status: {status} | elapsed: {elapsed:.2f}s")
    if err:
        print(f"  err: {err}")
    if status == "OK" and df is not None:
        show(df, "5)")
        net_cols = find_net_profit_columns(df)
        print(f"  🔎 含'净利'的列: {net_cols}")

    print("\n" + "=" * 70)
    print("🎯 探测完成。请查看哪个接口能拿到茅台 (600519) 净利润。")
    print("=" * 70)


if __name__ == "__main__":
    main()
