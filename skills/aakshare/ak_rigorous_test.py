#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ak_rigorous_test.py — AKShare 核心数据源严谨性基准测试 (v3 突围版)

Frank 指令（2026-06-02 19:22）4 点突围 + v3 增强：
  1. 锁死 bond_zh_us_rate() 作为美债真理源
  2. 攻克 A 股行情反爬虫：东财+新浪+ hq.sinajs.cn 三源备份
  3. 修正 stock_notice_report() symbol='全部' + date='20260601' + 二次过滤
  4. FRED 在国内 GFW 屏蔽 → macro_usa_cpi_yoy + bond_gb_us_sina 替代
  + hq.sinajs.cn 直接 requests 抓取（金融圈最稳的实时行情接口）

测试环境：
  - akshare v1.18.35
  - Python 3.9
  - 仓内 aakshare skill 独立测试，零污染生产代码
"""

import time
import requests
import akshare as ak
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def audit_dataframe(name, df, expected_cols_min=2):
    """严谨审计返回的数据结构"""
    if df is None or df.empty:
        raise ValueError(f"【致命】{name} 接口返回了空数据！")
    print(f"✅ {name} 测试通过 | 数据行数: {len(df)} | 列名预览: {list(df.columns[:5])}")
    print(f"📊 数据切片预览:\n{df.head(2).to_string()}\n" + "-" * 50)


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


def report(name, status, df, elapsed, err=None, extra=""):
    if status == "OK":
        if df is None or df.empty:
            print(f"❌ {name} | 空数据 | {elapsed:.2f}s{extra}")
            return
        print(f"⏱️ {name} | 耗时 {elapsed:.2f}s | rows={len(df)} | cols={list(df.columns[:5])}")
        if extra:
            print(f"   {extra}")
    else:
        print(f"❌ {name} | {err} | {elapsed:.2f}s")


# ══════════════════════════════════════════════════════════════════════════════
# 目标 1: A 股实时行情 (三源备份)
# ══════════════════════════════════════════════════════════════════════════════

def test_a_stock_three_sources():
    """A 股实时行情 - 东财 + akshare新浪 + hq.sinajs.cn 直接抓"""
    print("\n【目标 1: A 股实时行情 (东财 + akshare 新浪 + hq.sinajs.cn 三源)】")

    # 1a) stock_zh_a_spot_em（注入完整 headers）
    try:
        import requests as _req
        _real_get = _req.get
        def _patched_get(url, **kw):
            kw.setdefault("headers", {})
            kw["headers"].update({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://quote.eastmoney.com/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
            return _real_get(url, **kw)
        _req.get = _patched_get
        status, df, elapsed, err = try_call("1a) stock_zh_a_spot_em", ak.stock_zh_a_spot_em)
    finally:
        _req.get = _real_get
    report("1a) stock_zh_a_spot_em(headers 注入)", status, df, elapsed, err)
    if status == "OK" and not df.empty:
        try:
            audit_dataframe("1a) stock_zh_a_spot_em", df)
        except Exception as e:
            print(f"   (审计: {e})")

    # 1b) stock_zh_a_spot（akshare 新浪源 — 注意限速）
    status, df, elapsed, err = try_call("1b) stock_zh_a_spot(akshare 新浪)", ak.stock_zh_a_spot)
    report("1b) stock_zh_a_spot(akshare 新浪)", status, df, elapsed, err)
    if status == "OK" and not df.empty:
        m_out = df[df['代码'] == 'sh600519'] if '代码' in df.columns else pd.DataFrame()
        if not m_out.empty:
            print(f"   📌 茅台(sh600519) 行情: 最新价={m_out.iloc[0].get('最新价')} 时间戳={m_out.iloc[0].get('时间戳')}")

    # 1c) hq.sinajs.cn 直接抓（金融圈最稳的实时接口，0.06s 拿到 9 个核心标的）
    print("\n   1c) 新浪 hq.sinajs.cn 直接抓 (金融圈最稳):")
    codes = [
        "sh000001",  # 上证指数
        "sz399001",  # 深证成指
        "sz399006",  # 创业板指
        "sh000688",  # 科创 50
        "sh600519",  # 贵州茅台
        "sz000001",  # 平安银行
        "sh600036",  # 招商银行
        "sh601318",  # 中国平安
        "sz000858",  # 五粮液
    ]
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    url = f"https://hq.sinajs.cn/list=" + ",".join(codes)
    start = time.time()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        elapsed = time.time() - start
        if resp.status_code == 200:
            print(f"   ✅ hq.sinajs.cn HTTP 200 | {elapsed:.3f}s | {len(resp.text)} bytes")
            for line in resp.text.strip().split('\n'):
                if '=' in line:
                    var, val = line.split('=', 1)
                    code = var.replace('var hq_str_', '').strip()
                    vals = val.strip().strip(';').strip('"').split(',')
                    if len(vals) >= 6:
                        # 新浪 hq.sinajs.cn 字段顺序 (v3 修正):
                        #   [0] 名称
                        #   [1] 今日开盘价 (⚠️ 不是现价!)
                        #   [2] 昨日收盘价
                        #   [3] 当前价 (实时/最新) ← Frank 2026-06-03 16:25 纠错：必须用 [3]
                        #   [4] 今日最高价
                        #   [5] 今日最低价
                        print(f"      {code:>10} | {vals[0]:<10} | 开盘={vals[1]:>8} | 昨收={vals[2]} | 现价={vals[3]:>8} | 最高={vals[4]} | 最低={vals[5]}")
        else:
            print(f"   ❌ HTTP {resp.status_code}")
    except Exception as e:
        print(f"   ❌ {type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 主测试流程
# ══════════════════════════════════════════════════════════════════════════════

def run_rigorous_test():
    print("🚀 开始执行 AKShare 严谨性基准测试 v3 (突围+三源)...\n" + "=" * 60)
    print(f"📌 akshare v{ak.__version__} | Frank 4 点指令对齐 + hq.sinajs.cn 增强")
    print("=" * 60)

    # 目标 1: A 股实时行情 (三源)
    test_a_stock_three_sources()

    # 目标 2: A 股个股财务指标 (Frank 原名 — 已知空数据)
    print("\n【目标 2: A 股个股财务指标 (Frank 原名 — 已知空数据)】")
    status, df, elapsed, err = try_call(
        "2) stock_financial_analysis_indicator(600519)",
        ak.stock_financial_analysis_indicator, symbol="600519"
    )
    report("2) stock_financial_analysis_indicator", status, df, elapsed, err)

    # 目标 3: A 股个股官方公告 (修正 symbol+date+二次过滤)
    print("\n【目标 3: A 股个股官方公告 (修正 symbol+date+二次过滤)】")
    status, df, elapsed, err = try_call(
        "3) stock_notice_report(symbol='全部', date='20260601')",
        ak.stock_notice_report, symbol="全部", date="20260601"
    )
    report("3) stock_notice_report(修正)", status, df, elapsed, err)
    if status == "OK" and not df.empty:
        m_out = df[df['代码'] == '600519']
        print(f"   二次过滤 [代码=='600519']: rows={len(m_out)}")
        if not m_out.empty:
            print(f"   📌 茅台公告: {m_out.head(3).to_string()}")
        else:
            # 试前几天
            for prev_date in ['20260530', '20260529', '20260528']:
                prev_df = ak.stock_notice_report(symbol='全部', date=prev_date)
                m_prev = prev_df[prev_df['代码'] == '600519']
                if not m_prev.empty:
                    print(f"   📌 前几天 ({prev_date}) 茅台公告:")
                    print(m_prev.head(3).to_string())
                    break
            else:
                print(f"   ⚠️ 最近 4 个交易日茅台无公告（属正常）")

    # 目标 4-5: 美联储利率 + CPI (FRED GFW 屏蔽 + 突围)
    print("\n【目标 4-5: 美联储利率 + CPI (FRED GFW 屏蔽)】")
    status, df, elapsed, err = try_call("4) fred_md('2024-12')", ak.fred_md, "2024-12")
    report("4) fred_md (GFW 屏蔽)", status, df, elapsed, err)
    status, df, elapsed, err = try_call("5) fred_qd('2024-12')", ak.fred_qd, "2024-12")
    report("5) fred_qd (GFW 屏蔽)", status, df, elapsed, err)

    print("\n【突围 4′: macro_bank_usa_interest_rate (akshare 内置)】")
    status, df, elapsed, err = try_call("4′) macro_bank_usa_interest_rate", ak.macro_bank_usa_interest_rate)
    if status == "OK" and not df.empty:
        try:
            audit_dataframe("4′) macro_bank_usa_interest_rate", df)
        except Exception as e:
            print(f"   (审计: {e})")
    report("4′) macro_bank_usa_interest_rate", status, df, elapsed, err)

    print("\n【突围 5′: macro_usa_cpi_yoy (比 cpi_monthly 新 7-8 个月)】")
    status, df, elapsed, err = try_call("5′) macro_usa_cpi_yoy", ak.macro_usa_cpi_yoy)
    if status == "OK" and not df.empty:
        try:
            audit_dataframe("5′) macro_usa_cpi_yoy", df)
        except Exception as e:
            print(f"   (审计: {e})")
    report("5′) macro_usa_cpi_yoy", status, df, elapsed, err)

    # 目标 6: 美国国债收益率 (锁死双源)
    print("\n【目标 6: 美国国债收益率 (锁死 bond_zh_us_rate + bond_gb_us_sina 双源)】")
    status, df, elapsed, err = try_call("6) bond_zh_us_rate (主源 — 锁死)", ak.bond_zh_us_rate)
    if status == "OK" and not df.empty:
        try:
            audit_dataframe("6) bond_zh_us_rate (锁死)", df)
        except Exception as e:
            print(f"   (审计: {e})")
        if '美国国债收益率10年' in df.columns:
            latest = df[['日期', '美国国债收益率10年']].dropna().tail(1)
            if not latest.empty:
                print(f"   📌 最新美国 10Y: {latest.iloc[0].to_dict()}")
    report("6) bond_zh_us_rate", status, df, elapsed, err)

    status, df, elapsed, err = try_call("6′) bond_gb_us_sina (新浪备份)", ak.bond_gb_us_sina)
    if status == "OK" and not df.empty:
        try:
            audit_dataframe("6′) bond_gb_us_sina (备份源)", df)
        except Exception as e:
            print(f"   (审计: {e})")
    report("6′) bond_gb_us_sina", status, df, elapsed, err)

    print("\n" + "=" * 60)
    print("🎯 v3 测试完成。汇总：6 个核心数据点 + 三源备份 + hq.sinajs.cn 稳定抓取")
    print("=" * 60)


if __name__ == "__main__":
    run_rigorous_test()
