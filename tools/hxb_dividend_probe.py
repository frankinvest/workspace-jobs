#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hxb_dividend_probe.py — 华夏银行 (600015) 3 年期红利基本面自检 (修正版)

Frank 2026-06-03 17:25 指令:
  1. 定量基本面: financial_data_hub.fetch_financial_abstract('600015')
  2. 分红派息率: ak.stock_fhps_em(date=YYYY1231) — 3 年
  3. 文本挖掘: financial_data_hub.fetch_stock_notices('600015') + web_fetch 抓公告

⚠️ 透明纠错 (与 Frank 提示差异):
  - ak.stock_fhps_em 实际签名是 (date='YYYYMMDD'), 不是 (symbol='...')
  - "现金分红-现金分红比例" 实际是 "每 10 股税前红利(元)"
  - 归母净利润指标在 abstract 中是 "归母净利润" (不是 "归属于母公司所有者的净利润")
  - 600015 年报实际发布日: 2024-04-30 / 2025-04-18 / 2026-03-31
"""
import sys
import time
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, 'tools')
from financial_data_hub import FinancialDataHub
import akshare as ak
import pandas as pd


def get_fundamentals_3y(symbol: str = '600015'):
    """[1] 定量基本面 - 3 年营收/净利/EPS"""
    print("\n" + "=" * 70)
    print("📊 [1] 定量基本面 (3 年) — financial_data_hub.fetch_financial_abstract")
    print("=" * 70)
    hub = FinancialDataHub(verbose=False)
    df = hub.fetch_financial_abstract(symbol)
    print(f"  rows={len(df)}, 80 季度序列")

    year_cols = ['20231231', '20241231', '20251231']
    year_labels = {'20231231': '2023', '20241231': '2024', '20251231': '2025'}

    # 修正: 600015 abstract 实际指标名是 "归母净利润" / "营业总收入" / "基本每股收益"
    metric_keys = ['营业总收入', '归母净利润', '基本每股收益']

    result = {}
    for col in year_cols:
        result[col] = {}
        for key in metric_keys:
            r = df[df['指标'].str.contains(key, na=False)]
            if not r.empty:
                val = r[col].iloc[0]
                result[col][key] = val
                unit = '元' if key == '基本每股收益' else '元'
                print(f"  {year_labels[col]} {key}: {val} {unit}")
            else:
                result[col][key] = None
                print(f"  {year_labels[col]} {key}: ❌ 找不到")

    return result


def get_dividends_3y(symbol: str = '600015'):
    """[2] 分红 + 派息率精准计算 — ak.stock_fhps_em"""
    print("\n" + "=" * 70)
    print("💰 [2] 分红 + 派息率 (3 年) — ak.stock_fhps_em(date)")
    print("=" * 70)
    print("  公式: 每股红利 = 每10股税前红利 / 10; 派息率 = 每股红利 / EPS")

    year_dates = ['20231231', '20241231', '20251231']
    year_labels = {'20231231': '2023', '20241231': '2024', '20251231': '2025'}

    result = {}
    for date_str in year_dates:
        print(f"\n--- {year_labels[date_str]} 年报 (报告期 {date_str}) ---")
        df = ak.stock_fhps_em(date=date_str)
        sub = df[df['代码'] == symbol]
        if sub.empty:
            print(f"  ❌ {symbol} 无分红数据")
            continue

        row = sub.iloc[0]
        per_10sh = float(row['现金分红-现金分红比例'])  # 每 10 股税前红利
        per_sh = per_10sh / 10
        eps = float(row['每股收益'])
        payout_ratio = per_sh / eps if eps else 0
        div_yield = float(row['现金分红-股息率'])

        result[date_str] = {
            'per_10sh': per_10sh,
            'per_sh': per_sh,
            'eps': eps,
            'payout_ratio': payout_ratio,
            'div_yield': div_yield,
            'announce_date': str(row['预案公告日']),
            'status': str(row['方案进度']),
        }

        print(f"  每10股税前红利: ¥{per_10sh:.4f} 元")
        print(f"  每股红利: ¥{per_sh:.4f} 元 (= {per_10sh} ÷ 10)")
        print(f"  基本每股收益: ¥{eps:.2f} 元")
        print(f"  派息率: {payout_ratio*100:.2f}%")
        print(f"  股息率: {div_yield*100:.2f}%")
        print(f"  预案公告日: {row['预案公告日']}")
        print(f"  方案进度: {row['方案进度']}")

    return result


def get_targeted_notices(symbol: str = '600015'):
    """[3] 文本挖掘 - 精准日期的年报+利润分配公告"""
    print("\n" + "=" * 70)
    print("📜 [3] 公告过滤 - 3 年年报+利润分配 (精准日期)")
    print("=" * 70)

    hub = FinancialDataHub(verbose=False)
    # 3 年实际年报发布日 (从分红数据反推)
    target_dates = [
        ('2023 年报', '20240430', '2024-04-30'),
        ('2024 年报', '20250418', '2025-04-18'),
        ('2025 年报', '20260331', '2026-03-31'),
    ]

    all_filtered = []
    for label, date_str, display_date in target_dates:
        print(f"\n--- {label} (实际发布 {display_date}) ---")
        df = hub.fetch_stock_notices('全部', date_str)
        sub = df[df['代码'] == symbol]
        if sub.empty:
            print(f"  ❌ {symbol} 无公告")
            continue
        print(f"  {symbol} 当日公告: {len(sub)} 条")
        # 过滤年度报告/利润分配
        keywords = '年度报告|利润分配'
        filtered = sub[sub['公告标题'].str.contains(keywords, na=False)]
        print(f"  含'年报/利润分配': {len(filtered)} 条")
        for idx, row in filtered.iterrows():
            print(f"  📌 {row['公告日期']} | {row['公告标题']}")
            if '网址' in row:
                print(f"     🔗 {row['网址']}")
            all_filtered.append({
                'year': label,
                'date': str(row['公告日期']),
                'title': row['公告标题'],
                'url': row.get('网址', ''),
            })

    return all_filtered


def main():
    print("=" * 70)
    print("🏦 华夏银行 (600015) 3 年期红利基本面全景自检")
    print(f"⏰ 报告生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 1. 定量基本面
    fundamentals = get_fundamentals_3y('600015')

    # 2. 分红 + 派息率
    dividends = get_dividends_3y('600015')

    # 3. 公告
    notices = get_targeted_notices('600015')

    # 汇总
    import json
    summary = {
        'symbol': '600015',
        'name': '华夏银行',
        'fundamentals': fundamentals,
        'dividends': dividends,
        'notices': notices,
    }
    with open('/tmp/hxb_dividend_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print("\n" + "=" * 70)
    print("📁 汇总数据已保存到 /tmp/hxb_dividend_summary.json")
    print("=" * 70)


if __name__ == "__main__":
    main()
