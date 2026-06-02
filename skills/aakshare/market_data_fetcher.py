#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_data_fetcher.py — A 股历史日线数据封装（带日期校验锁 + 退避重试）

Frank 指令（2026-06-02 23:00）：
  原 v3 测试使用 stock_zh_a_spot_em() 盘中实时接口，早 8:00 cron 跑时市场未开盘
  → 拿到的是"上一个交易日的滞后数据"或"今日模拟数据"，**完全张冠李戴**。

本封装：
  1. 严禁使用 stock_zh_a_spot_em() 盘中实时接口
  2. 统一改用 stock_zh_a_hist() 历史日线接口，**显式传入精确日期**
  3. 强行注入【日期校验锁】：
     - 拿到的 DataFrame 必须校验"日期"字段
     - 如果返回的最新日期 < 请求日期 → 报警"今日尚未收盘或数据未更新"
     - 如果返回的最新日期 == 请求日期 → 标记"✅ 真实收盘数据"
     - 如果返回的日期 > 请求日期 → 报警"接口返回了未来数据（异常）"
  4. 【退避重试】东方财富对短时间内连续请求限速，加 3/6/12s 指数退避
  5. 6 场景自检覆盖：今日/昨日/周末/茅台/跨日/未来错填

生产代码：零污染，不修改任何现有文件。
"""

import sys
import time
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Tuple, Any
import akshare as ak
import pandas as pd


# ══════════════════════════════════════════════════════════════════════════════
# 常量与辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def to_yyyymmdd(d) -> str:
    """任意 datetime/date 转 'YYYYMMDD'"""
    if isinstance(d, str):
        return d.replace("-", "").replace("/", "")
    return d.strftime("%Y%m%d")


def to_iso_date(d) -> str:
    """任意 datetime/date 转 'YYYY-MM-DD'"""
    if isinstance(d, str):
        return d[:10]  # 兼容 '20260602' / '2026-06-02'
    return d.strftime("%Y-%m-%d")


def is_trading_day(d: date) -> bool:
    """A 股交易日判断（粗略：排除周末）
    注：法定节假日需另外查表，本函数只排除周六周日。"""
    return d.weekday() < 5  # 0-4 = Mon-Fri


# ══════════════════════════════════════════════════════════════════════════════
# 退避重试包装
# ══════════════════════════════════════════════════════════════════════════════

def _call_with_retry(fn, *args, max_retries: int = 3, base_delay: float = 3.0, verbose: bool = True, **kwargs):
    """带指数退避的重试包装：失败 1 次等 3s，2 次等 6s，3 次等 12s

    专门针对东方财富 / 新浪的限速（短时间内连续请求会 ConnectionError）
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))  # 3, 6, 12
                if verbose:
                    print(f"  ⚠️ 第 {attempt}/{max_retries} 次失败 ({type(e).__name__}: {str(e)[:80]})，{delay}s 后重试...")
                time.sleep(delay)
    raise last_exc


# ══════════════════════════════════════════════════════════════════════════════
# 核心：日期校验锁
# ══════════════════════════════════════════════════════════════════════════════

class DateGuardViolation(Exception):
    """日期校验失败异常（接口返回未来数据）"""
    pass


def validate_date_guard(df: pd.DataFrame, requested_date: str) -> Dict:
    """
    严格校验 DataFrame 的日期字段是否匹配请求日期。

    Args:
        df: stock_zh_a_hist 返回的 DataFrame
        requested_date: 调用方请求的日期 ('YYYY-MM-DD' 或 'YYYYMMDD')

    Returns:
        Dict 含:
          - status: 'OK' | 'STALE' | 'EMPTY' | 'FUTURE' | 'NON_TRADING_DAY' | 'ERROR'
          - requested_date: 规范化的请求日期
          - actual_date: 实际返回的最新日期（如果有）
          - message: 给调用方看的警告
          - df: 原始 DataFrame

    Raises:
        DateGuardViolation: 如果返回了未来数据（接口异常）
    """
    req_iso = to_iso_date(requested_date)
    req_date = datetime.strptime(req_iso, "%Y-%m-%d").date()

    # 规则 1: df 为空
    if df is None or df.empty:
        # 检查是不是非交易日
        if not is_trading_day(req_date):
            return {
                "status": "NON_TRADING_DAY",
                "requested_date": req_iso,
                "actual_date": None,
                "message": (
                    f"⚠️ {req_iso} 是 {['周一','周二','周三','周四','周五','周六','周日'][req_date.weekday()]}，"
                    f"A 股休市（周末）。请选择最近一个交易日重试。"
                ),
                "df": df,
            }
        # 早请求 / 数据未更新
        return {
            "status": "STALE",
            "requested_date": req_iso,
            "actual_date": None,
            "message": (
                f"⚠️ 今日 A 股尚未收盘或数据未更新（请求 {req_iso}，接口返回空）。"
                f"当前返回为【前一个交易日】的最终数据。请在 A 股收盘 15:00 后重试。"
            ),
            "df": df,
        }

    # 取 DataFrame 的日期列（stock_zh_a_hist 用 '日期' 列）
    if '日期' not in df.columns:
        return {
            "status": "EMPTY",
            "requested_date": req_iso,
            "actual_date": None,
            "message": f"⚠️ 返回的 DataFrame 没有 '日期' 列，无法做日期校验。",
            "df": df,
        }

    actual_date_str = str(df['日期'].max())  # 形如 '2026-06-02'
    actual_date = datetime.strptime(actual_date_str, "%Y-%m-%d").date()

    # 规则 4: 未来数据（异常，抛错）
    if actual_date > req_date:
        raise DateGuardViolation(
            f"🚨 接口返回了未来数据：请求 {req_iso}，返回 {actual_date_str}。"
            f"这通常是 akshare 接口异常或上游数据源时区错位，请人工核查。"
        )

    # 规则 3: 真实数据（已收盘）
    if actual_date == req_date:
        return {
            "status": "OK",
            "requested_date": req_iso,
            "actual_date": actual_date_str,
            "message": f"✅ {req_iso} 已收盘，真实数据。",
            "df": df,
        }

    # 规则 2: 滞后（早 8 点调用了今日，但接口只到昨日）
    return {
        "status": "STALE",
        "requested_date": req_iso,
        "actual_date": actual_date_str,
        "message": (
            f"⚠️ 今日 A 股尚未收盘或数据未更新！\n"
            f"   请求日期: {req_iso}\n"
            f"   实际最新: {actual_date_str}（比请求晚 { (req_date - actual_date).days } 天）\n"
            f"   当前返回为【{actual_date_str} 最终数据】，不是 {req_iso} 的数据！\n"
            f"   请在 A 股收盘（每个交易日 15:00）后再调取，或显式改用 date='{actual_date_str}'。"
        ),
        "df": df,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════════════════════════════════════

def fetch_a_stock_daily(
    symbol: str,
    date: Optional[str] = None,
    *,
    adjust: str = "qfq",
    timeout: float = 15.0,
    max_retries: int = 3,
    verbose: bool = True,
) -> Dict:
    """
    获取单只 A 股指定日期的日线数据（带日期校验锁 + 退避重试）。

    Args:
        symbol: 股票代码（6 位，不带 sh/sz 前缀）
        date: 请求日期（'YYYY-MM-DD' 或 'YYYYMMDD'），默认今天
        adjust: 复权方式（'qfq' 前复权, 'hfq' 后复权, '' 不复权）
        timeout: HTTP 超时
        max_retries: 最大重试次数（默认 3）
        verbose: 是否打印重试日志

    Returns:
        Dict 含:
          - symbol
          - date_guard: validate_date_guard 的返回值
          - close, open, high, low, change_pct, volume, amount: 核心字段
          - elapsed: 耗时
    """
    if date is None:
        date = date.today().strftime("%Y-%m-%d")

    yyyymmdd = to_yyyymmdd(date)
    start = time.time()
    try:
        df = _call_with_retry(
            ak.stock_zh_a_hist,
            symbol=symbol,
            period="daily",
            start_date=yyyymmdd,
            end_date=yyyymmdd,
            adjust=adjust,
            timeout=timeout,
            max_retries=max_retries,
            verbose=verbose,
        )
        elapsed = time.time() - start
    except Exception as e:
        return {
            "symbol": symbol,
            "date_guard": {
                "status": "ERROR",
                "requested_date": to_iso_date(date),
                "actual_date": None,
                "message": f"❌ 接口异常 ({max_retries} 次重试后): {type(e).__name__}: {e}",
                "df": pd.DataFrame(),
            },
            "elapsed": round(time.time() - start, 3),
        }

    # 强制日期校验锁
    guard = validate_date_guard(df, date)

    # 提取核心字段
    result = {
        "symbol": symbol,
        "date_guard": guard,
        "elapsed": round(elapsed, 3),
    }
    if not df.empty and len(df) > 0:
        row = df.iloc[0]
        result.update({
            "date": str(row.get("日期")),
            "open": float(row.get("开盘", 0)),
            "close": float(row.get("收盘", 0)),
            "high": float(row.get("最高", 0)),
            "low": float(row.get("最低", 0)),
            "volume": int(row.get("成交量", 0)),
            "amount": float(row.get("成交额", 0)),
            "change_pct": float(row.get("涨跌幅", 0)),
            "change_amt": float(row.get("涨跌额", 0)),
            "turnover": float(row.get("换手率", 0)),
            "amplitude": float(row.get("振幅", 0)),
        })
    return result


def fetch_a_stock_range(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    adjust: str = "qfq",
    timeout: float = 15.0,
    max_retries: int = 3,
) -> Dict:
    """
    获取 A 股在 [start_date, end_date] 区间内的全部日线数据（带重试）。

    Returns:
        Dict 含:
          - date_guard: 区间最后一日的 guard
          - rows: 全部行 DataFrame
          - summary: 区间统计（区间收益、最大回撤等）
          - elapsed
    """
    start_yyyymmdd = to_yyyymmdd(start_date)
    end_yyyymmdd = to_yyyymmdd(end_date)
    start = time.time()
    try:
        df = _call_with_retry(
            ak.stock_zh_a_hist,
            symbol=symbol,
            period="daily",
            start_date=start_yyyymmdd,
            end_date=end_yyyymmdd,
            adjust=adjust,
            timeout=timeout,
            max_retries=max_retries,
        )
        elapsed = time.time() - start
    except Exception as e:
        return {
            "symbol": symbol,
            "date_guard": {"status": "ERROR", "message": f"❌ {type(e).__name__}: {e}", "df": pd.DataFrame()},
            "rows": pd.DataFrame(),
            "summary": {},
            "elapsed": round(time.time() - start, 3),
        }

    # 区间校验：最后一日的 guard
    if not df.empty and '日期' in df.columns:
        last_date = str(df['日期'].max())
        guard = validate_date_guard(df, last_date)
    else:
        guard = validate_date_guard(df, end_date)

    # 区间统计
    summary = {}
    if not df.empty and len(df) > 1:
        first_close = float(df.iloc[0].get("收盘", 0))
        last_close = float(df.iloc[-1].get("收盘", 0))
        summary = {
            "rows": len(df),
            "first_date": str(df['日期'].min()),
            "last_date": str(df['日期'].max()),
            "first_close": first_close,
            "last_close": last_close,
            "range_change_pct": round(
                (last_close / first_close - 1) * 100, 2
            ) if first_close else 0,
        }

    return {
        "symbol": symbol,
        "date_guard": guard,
        "rows": df,
        "summary": summary,
        "elapsed": round(elapsed, 3),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 测试 / 自检
# ══════════════════════════════════════════════════════════════════════════════

def self_test():
    """6 场景自检"""
    print("=" * 70)
    print(f"🧪 market_data_fetcher 自检 | 当前时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 场景 1: 今日 6/2 (已收盘 23:00 后)
    print("\n【场景 1】请求 2026-06-02 平安银行 000001 (今日已收盘，应是 OK)")
    r1 = fetch_a_stock_daily("000001", date="20260602")
    print(f"  状态: {r1['date_guard']['status']}")
    print(f"  消息: {r1['date_guard']['message']}")
    if 'close' in r1:
        print(f"  数据: 日期={r1['date']} 开盘={r1['open']} 收盘={r1['close']} 最高={r1['high']} 涨跌幅={r1['change_pct']}%")
    print(f"  耗时: {r1['elapsed']}s")

    # 场景 2: 昨日 6/1 (已收盘)
    print("\n【场景 2】请求 2026-06-01 平安银行 (昨日已收盘，应是 OK)")
    r2 = fetch_a_stock_daily("000001", date="20260601")
    print(f"  状态: {r2['date_guard']['status']}")
    print(f"  消息: {r2['date_guard']['message']}")
    if 'close' in r2:
        print(f"  数据: 日期={r2['date']} 开盘={r2['open']} 收盘={r2['close']} 涨跌幅={r2['change_pct']}%")

    # 场景 3: 周末
    print("\n【场景 3】请求 2026-05-31 (周日，非交易日，应是 NON_TRADING_DAY)")
    r3 = fetch_a_stock_daily("000001", date="20260531")
    print(f"  状态: {r3['date_guard']['status']}")
    print(f"  消息: {r3['date_guard']['message']}")

    # 场景 4: 茅台 600519 今日
    print("\n【场景 4】请求茅台 600519 在 2026-06-02 (今日)")
    r4 = fetch_a_stock_daily("600519", date="20260602")
    print(f"  状态: {r4['date_guard']['status']}")
    print(f"  消息: {r4['date_guard']['message']}")
    if 'close' in r4:
        print(f"  数据: 日期={r4['date']} 开盘={r4['open']} 收盘={r4['close']} 涨跌幅={r4['change_pct']}%")

    # 场景 5: 跨日范围 5/26-6/2
    print("\n【场景 5】跨日范围 2026-05-26 至 2026-06-02 (茅台 6 行)")
    r5 = fetch_a_stock_range("600519", "20260526", "20260602")
    print(f"  状态: {r5['date_guard']['status']}")
    print(f"  消息: {r5['date_guard']['message']}")
    print(f"  区间: {r5['summary']}")

    # 场景 6: 未来错填日期
    print("\n【场景 6】错填日期 (请求 2026-12-31，2027 年，接口空)")
    r6 = fetch_a_stock_daily("000001", date="20261231")
    print(f"  状态: {r6['date_guard']['status']}")
    print(f"  消息: {r6['date_guard']['message']}")

    print("\n" + "=" * 70)
    print("✅ 自检完成")
    print("=" * 70)


if __name__ == "__main__":
    self_test()
