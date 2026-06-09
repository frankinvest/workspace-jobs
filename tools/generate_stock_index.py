#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_stock_index.py - 沪深京全量 A 股代码 + 名称 + 现价 静态字典生成器

【Frank 2026-06-09 数据字典升级】
- 在 code/name 基础上新增 "price" 字段
- api/dividend.py 不再调腾讯 qt.gtimg.cn, 直接从 stock_index.json 读 price
- 实现"数据离线落库, 后端轻量直读"纯净底座

【数据源 (智能 fallback)】
- 优先: ak.stock_zh_a_spot_em (Frank 指定的东财源, 含价格)
- Fallback A: ak.stock_zh_a_spot (新浪, 含价格 + 北交所 bj920xxx)
- Fallback B: requests 直调 hq.sinajs.cn 批量 (sandbox 网络隔离下唯一可用的全市场源)

【价格层叠补全】
1. 优先从 akshare DataFrame['最新价'] 拿 (如有)
2. akshare 失败时用 requests 调 hq.sinajs.cn (80 股票/批) 补全
3. 全部失败: price = 0.0 (停牌/失败占位)

【输出 schema】
[
  {"code": "600519", "name": "贵州茅台", "price": 1256.00},
  ...
]
"""
import json
import os
import sys
import time
from pathlib import Path

try:
    import akshare as ak
    _AKSHARE_AVAILABLE = True
except Exception as _e:
    print(f"[generate] WARN: akshare 不可用: {type(_e).__name__}: {_e}", file=sys.stderr)
    _AKSHARE_AVAILABLE = False

import requests


# ── 市场前缀推导 (用于新浪 hq.sinajs.cn URL) ──────────────────────────────────
def _market_prefix(c: str) -> str:
    if c.startswith("6"):
        return "sh"
    if c.startswith(("0", "3")):
        return "sz"
    if c.startswith(("8", "4", "9")):
        return "bj"
    return "sh"


# ── requests 直调新浪批量接口 (sandbox 网络隔离下唯一稳的方案) ─────────────
def _fetch_prices_via_sina_http(codes: list, batch_size: int = 80) -> dict:
    """通过 hq.sinajs.cn 批量拉价格, 80 股票/批, 4-5s 拉 5500+"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    results = {}
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        url = "https://hq.sinajs.cn/list=" + ",".join(
            f"{_market_prefix(c)}{c}" for c in batch
        )
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            for line in r.text.split("\n"):
                if "=" not in line:
                    continue
                raw_code = line.split("=")[0].split("_")[-1]  # "sh600036"
                # 剥前缀 → 6 位代码
                if len(raw_code) > 6:
                    raw_code = raw_code[2:]
                content = line.split("=")[1].replace('"', "").replace(";", "")
                tokens = content.split(",")
                if len(tokens) < 4:
                    continue
                try:
                    price = float(tokens[3])
                    if price == 0:
                        # 停牌 fallback 用昨收
                        price = float(tokens[2]) if len(tokens) > 2 else 0.0
                    results[raw_code] = round(price, 2)
                except (ValueError, IndexError):
                    pass
        except Exception as e:
            print(f"  [generate] batch {i} exception: {type(e).__name__}: {e}", file=sys.stderr)
    return results


# ── akshare 拉全市场代码 + 名称 (含价格) ────────────────────────────────────
def _fetch_via_akshare():
    """智能 fallback: EM → 新浪"""
    # 1. 优先 Frank 指定的东财接口
    print("[generate] 优先尝试 ak.stock_zh_a_spot_em (东财, Frank 指定)...")
    t0 = time.time()
    try:
        df = ak.stock_zh_a_spot_em()
        print(f"[generate] ✅ 东财接口成功: {len(df)} 行, {time.time() - t0:.1f}s")
        return df, "stock_zh_a_spot_em (东财)"
    except Exception as e:
        print(f"[generate] ⚠️ 东财接口失败: {type(e).__name__}: {e}", file=sys.stderr)

    # 2. Fallback: 新浪接口
    print("[generate] Fallback: 尝试 ak.stock_zh_a_spot (新浪)...")
    t0 = time.time()
    try:
        df = ak.stock_zh_a_spot()
        print(f"[generate] ✅ 新浪接口成功: {len(df)} 行, {time.time() - t0:.1f}s")
        return df, "stock_zh_a_spot (新浪, 含 bj920xxx 北交所)"
    except Exception as e:
        print(f"[generate] ❌ 新浪接口也失败: {type(e).__name__}: {e}", file=sys.stderr)

    return None, None


def generate():
    print("[generate] 启动沪深京全量 A 股代码 + 名称 + 现价 静态库生成")
    print("[generate] ============================================")

    df = None
    src = None
    price_col = "最新价"  # akshare 列名

    # 第 1 步: 拉代码 + 名称 (akshare)
    if _AKSHARE_AVAILABLE:
        df, src = _fetch_via_akshare()
        if df is not None:
            # 适配列名
            code_col = "代码" if "代码" in df.columns else "code"
            name_col = "名称" if "名称" in df.columns else "name"
            price_col = "最新价" if "最新价" in df.columns else ("price" if "price" in df.columns else None)
            missing = [
                n for n, c in [("代码", code_col), ("名称", name_col), ("最新价", price_col)]
                if c is None
            ]
            if missing:
                print(f"[generate] ⚠️ akshare df 缺列 {missing}, 实际列: {list(df.columns)}", file=sys.stderr)
                df = None

    stock_list = []
    seen_codes = set()
    skipped = 0

    if df is not None:
        # 走 akshare 路径 (含价格)
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            name = str(row.get("名称", "")).strip()
            if not code or not name:
                skipped += 1
                continue
            if code in seen_codes:
                skipped += 1
                continue
            seen_codes.add(code)

            # Frank 核心逻辑: 清洗并安全转换现价, 防止停牌/NaN 错误
            try:
                raw_price = row.get(price_col, 0.0)
                if raw_price != raw_price or raw_price is None:
                    price = 0.0
                else:
                    price = round(float(raw_price), 2)
            except (TypeError, ValueError, Exception):
                price = 0.0

            stock_list.append({"code": code, "name": name, "price": price})
    else:
        # Fallback: 只拉代码+名称 (用 akshare code_name 接口), 价格走 sina http 批量
        if not _AKSHARE_AVAILABLE:
            print("[generate] ❌ akshare 完全不可用, 无法获取代码+名称", file=sys.stderr)
            return 1
        print("[generate] 走 fallback: ak.stock_info_a_code_name (无价格) + 新浪 HTTP 补价...")
        t0 = time.time()
        try:
            df = ak.stock_info_a_code_name()
            print(f"[generate] ✅ 基础代码表: {len(df)} 行, {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"[generate] ❌ 基础代码表也失败: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        for _, row in df.iterrows():
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            if not code or not name:
                skipped += 1
                continue
            if code in seen_codes:
                skipped += 1
                continue
            seen_codes.add(code)
            stock_list.append({"code": code, "name": name, "price": 0.0})
        src = "ak.stock_info_a_code_name (基础表) + 新浪 HTTP 批量补价"

    # 第 2 步: 用 requests 直调新浪补全/校验价格 (无论 akshare 是否成功都跑一次)
    print(f"[generate] 第 2 步: requests 直调新浪 hq.sinajs.cn 补全/校验 {len(stock_list)} 只价格...")
    t0 = time.time()
    codes = [s["code"] for s in stock_list]
    live_prices = _fetch_prices_via_sina_http(codes)
    print(f"[generate] 新浪 HTTP 拉取: {len(live_prices)} / {len(codes)} 价格, 耗时 {time.time() - t0:.1f}s")

    # 用新浪价格覆盖 (新浪更稳, akshare EM 在 sandbox 撞墙)
    sina_hit = 0
    for s in stock_list:
        if s["code"] in live_prices and live_prices[s["code"]] > 0:
            s["price"] = live_prices[s["code"]]
            sina_hit += 1
    print(f"[generate] 新浪价格覆盖: {sina_hit} / {len(stock_list)} 只")

    # 按代码升序排序
    stock_list.sort(key=lambda x: x["code"])

    output_path = Path.home() / ".openclaw" / "workspace-jobs" / "public" / "data" / "stock_index.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stock_list, f, ensure_ascii=False, indent=2)

    # 统计
    sh_main = sum(1 for s in stock_list if s["code"].startswith("60"))
    sh_kechuang = sum(1 for s in stock_list if s["code"].startswith("688"))
    sz_main = sum(1 for s in stock_list if s["code"].startswith("00"))
    sz_chuangye = sum(1 for s in stock_list if s["code"].startswith("30"))
    bj = sum(1 for s in stock_list if s["code"].startswith("bj"))
    has_price = sum(1 for s in stock_list if s["price"] > 0)

    print()
    print(f"[generate] ============================================")
    print(f"[generate] ✅ 成功导出 {len(stock_list)} 只沪深京股票至 {output_path}")
    print(f"[generate] 数据源组合: {src}")
    print(f"[generate]   沪市主板 (60xxxx):    {sh_main}")
    print(f"[generate]   沪市科创 (688xxx):    {sh_kechuang}")
    print(f"[generate]   深市主板 (00xxxx):    {sz_main}")
    print(f"[generate]   深市创业 (30xxxx):    {sz_chuangye}")
    print(f"[generate]   北交所 (bjxxxxx):    {bj}")
    print(f"[generate]   含价格 (>0):         {has_price} / {len(stock_list)} = {100 * has_price / len(stock_list):.1f}%")
    print(f"[generate]   跳过 (空/重):        {skipped}")
    print(f"[generate] 前 3: {stock_list[:3]}")
    print(f"[generate] 后 3: {stock_list[-3:]}")
    return 0


if __name__ == "__main__":
    sys.exit(generate())
