#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_stock_index.py - 沪深京全量 A 股代码 + 名称 + 现价 + 行业 静态字典生成器

【Frank 2026-06-09 数据字典再升级 v2】
- 在 code/name/price 基础上新增 "industry" 字段
- Schema 升级: {code, name, price, industry}
- api/dividend.py 用 industry 字段直读, 不再走代码前缀推断

【数据源 (智能 fallback)】
- 优先: ak.stock_zh_a_spot_em (Frank 指定, 含原生"行业"列)
- Fallback A: ak.stock_zh_a_spot (新浪, 有价格但无行业)
- Fallback B: ak.stock_info_a_code_name (基础代码表, 仅代码+名称)
- 价格层: requests 直调 hq.sinajs.cn 批量 (沙箱唯一稳的 5527 全市场源)

【行业分类 (智能降级)】
- 优先: 东方财富原生的"行业"列 (申万三级行业, 最精准)
- 撞墙: 用代码前缀粗粒度映射 (沪市主板/科创/创业/北交所)
- 末路径: "未分类"

【输出 schema】
[
  {"code": "600519", "name": "贵州茅台", "price": 1256.00, "industry": "酿酒行业"},
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


# ── 行业粗粒度映射 (Frank EM 接口撞墙时的降级方案) ───────────────────────────
def _industry_by_code_prefix(code: str) -> str:
    """代码前缀 → 粗粒度行业 (申万一级), 仅在 EM 接口撞墙时用

    兼容两种代码格式:
      - 纯 6 位数字: 600036 / 000001 / 300750 / 920992
      - 带市场前缀: sh600036 / sz000001 / sz300750 / bj920992
    """
    # 剥掉市场前缀 (如有)
    c = code
    for prefix in ("sh", "sz", "bj"):
        if c.startswith(prefix) and len(c) > 6:
            c = c[len(prefix):]
            break

    if c.startswith("60"):
        return "沪市主板"
    if c.startswith("688"):
        return "沪市科创板"
    if c.startswith("000"):
        return "深市主板"
    if c.startswith("001") or c.startswith("002"):
        return "深市主板/中小板"
    if c.startswith("003"):
        return "深市主板"
    if c.startswith("300"):
        return "深市创业板"
    if c.startswith(("83", "87", "920", "43", "82")):
        return "北交所"
    if c.startswith(("4", "8")):
        return "北交所"
    return "未分类"


# ── 市场前缀推导 (新浪 hq.sinajs.cn URL) ──────────────────────────────────────
def _market_prefix(c: str) -> str:
    if c.startswith("6"):
        return "sh"
    if c.startswith(("0", "3")):
        return "sz"
    if c.startswith(("8", "4", "9")):
        return "bj"
    return "sh"


# ── requests 直调新浪批量接口 (沙箱唯一稳的全市场价格源) ─────────────────────
def _fetch_prices_via_sina_http(codes: list, batch_size: int = 80) -> dict:
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
                raw_code = line.split("=")[0].split("_")[-1]
                if len(raw_code) > 6:
                    raw_code = raw_code[2:]
                content = line.split("=")[1].replace('"', "").replace(";", "")
                tokens = content.split(",")
                if len(tokens) < 4:
                    continue
                try:
                    price = float(tokens[3])
                    if price == 0:
                        price = float(tokens[2]) if len(tokens) > 2 else 0.0
                    results[raw_code] = round(price, 2)
                except (ValueError, IndexError):
                    pass
        except Exception as e:
            print(f"  [generate] batch {i} exception: {type(e).__name__}: {e}", file=sys.stderr)
    return results


# ── akshare 拉全市场代码 + 名称 + (理想情况) 行业 ──────────────────────────────
def _fetch_via_akshare():
    """智能 fallback: EM → 新浪 → 基础代码表 (代码+名称)"""
    # 1. 优先 Frank 指定的东财接口 (含原生"行业"列)
    print("[generate] 优先尝试 ak.stock_zh_a_spot_em (东财, Frank 指定, 含行业)...")
    t0 = time.time()
    try:
        df = ak.stock_zh_a_spot_em()
        print(f"[generate] ✅ 东财接口成功: {len(df)} 行, {time.time() - t0:.1f}s (含行业)")
        return df, "stock_zh_a_spot_em (东财, 含行业)", "em_with_industry"
    except Exception as e:
        print(f"[generate] ⚠️ 东财接口撞墙: {type(e).__name__}: {e}", file=sys.stderr)

    # 2. Fallback: 新浪 (无行业列)
    print("[generate] Fallback: ak.stock_zh_a_spot (新浪, 无行业)...")
    t0 = time.time()
    try:
        df = ak.stock_zh_a_spot()
        print(f"[generate] ✅ 新浪接口成功: {len(df)} 行, {time.time() - t0:.1f}s (无行业, 需代码前缀映射)")
        return df, "stock_zh_a_spot (新浪, 无行业)", "spot_no_industry"
    except Exception as e:
        print(f"[generate] ⚠️ 新浪接口也撞墙: {type(e).__name__}: {e}", file=sys.stderr)

    # 3. 最后 fallback: 基础代码表
    if not _AKSHARE_AVAILABLE:
        return None, None, None
    print("[generate] 最后 fallback: ak.stock_info_a_code_name (基础代码表, 无价格无行业)...")
    t0 = time.time()
    try:
        df = ak.stock_info_a_code_name()
        print(f"[generate] ✅ 基础代码表: {len(df)} 行, {time.time() - t0:.1f}s")
        return df, "stock_info_a_code_name (基础表)", "code_name_only"
    except Exception as e:
        print(f"[generate] ❌ 基础表也失败: {type(e).__name__}: {e}", file=sys.stderr)

    return None, None, None


def generate():
    print("[generate] 启动沪深京全量 A 股代码 + 名称 + 现价 + 行业 静态库生成 (v2)")
    print("[generate] ============================================")

    df, src, mode = _fetch_via_akshare()
    if df is None:
        print("[generate] ❌ 所有数据源均失败, 退出", file=sys.stderr)
        return 1

    # 适配列名
    code_col = "代码" if "代码" in df.columns else "code"
    name_col = "名称" if "名称" in df.columns else "name"
    price_col = "最新价" if "最新价" in df.columns else ("price" if "price" in df.columns else None)
    industry_col = "行业" if "行业" in df.columns else None

    has_industry_col = industry_col is not None
    print(f"[generate] 行业列: {industry_col or '(无, 用代码前缀映射)'}")

    stock_list = []
    seen_codes = set()
    skipped = 0

    for _, row in df.iterrows():
        code = str(row.get(code_col, "")).strip()
        name = str(row.get(name_col, "")).strip()
        if not code or not name:
            skipped += 1
            continue
        if code in seen_codes:
            skipped += 1
            continue
        seen_codes.add(code)

        # 1. 价格清洗 (Frank 核心逻辑 + NaN 隔离)
        try:
            raw_price = row.get(price_col, 0.0) if price_col else 0.0
            if raw_price != raw_price or raw_price is None:
                price = 0.0
            else:
                price = round(float(raw_price), 2)
        except (TypeError, ValueError, Exception):
            price = 0.0

        # 2. 行业分类清洗 (Frank 核心逻辑 + 智能降级)
        if has_industry_col:
            try:
                raw_industry = row.get(industry_col, "未分类")
                # NaN 检测 + 真值判断
                if raw_industry == raw_industry and raw_industry:
                    industry = str(raw_industry).strip()
                    if not industry:
                        industry = "未分类"
                else:
                    industry = "未分类"
            except Exception:
                industry = "未分类"
        else:
            # EM 接口撞墙: 用代码前缀粗粒度映射
            industry = _industry_by_code_prefix(code)

        stock_list.append({
            "code": code,
            "name": name,
            "price": price,
            "industry": industry,
        })

    # 第 2 步: requests 直调新浪补全/校验价格 (无论 akshare 是否成功都跑)
    print(f"[generate] 第 2 步: requests 直调新浪补全/校验 {len(stock_list)} 只价格...")
    t0 = time.time()
    codes = [s["code"] for s in stock_list]
    live_prices = _fetch_prices_via_sina_http(codes)
    print(f"[generate] 新浪 HTTP: {len(live_prices)} / {len(codes)} 价格, 耗时 {time.time() - t0:.1f}s")
    sina_hit = 0
    for s in stock_list:
        if s["code"] in live_prices and live_prices[s["code"]] > 0:
            s["price"] = live_prices[s["code"]]
            sina_hit += 1
    print(f"[generate] 新浪价格覆盖: {sina_hit} / {len(stock_list)} 只")

    # 按代码升序排序
    stock_list.sort(key=lambda x: x["code"])

    # 写入
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
    has_industry_real = sum(1 for s in stock_list if s["industry"] not in ("未分类", "沪市主板", "沪市科创板", "深市主板", "深市主板/中小板", "深市创业板", "北交所"))
    has_industry_coarse = sum(1 for s in stock_list if s["industry"] in ("沪市主板", "沪市科创板", "深市主板", "深市主板/中小板", "深市创业板", "北交所"))

    print()
    print(f"[generate] ============================================")
    print(f"[generate] ✅ 成功导出 {len(stock_list)} 只股票至 {output_path}")
    print(f"[generate] 数据源: {src}")
    print(f"[generate] 行业模式: {'EM 原生 (含三级行业)' if has_industry_col else '代码前缀粗粒度映射'}")
    print(f"[generate]   沪市主板 (60xxxx):   {sh_main}")
    print(f"[generate]   沪市科创 (688xxx):   {sh_kechuang}")
    print(f"[generate]   深市主板 (00xxxx):   {sz_main}")
    print(f"[generate]   深市创业 (30xxxx):   {sz_chuangye}")
    print(f"[generate]   北交所 (bjxxxxx):   {bj}")
    print(f"[generate]   含价格 (>0):        {has_price} / {len(stock_list)}")
    print(f"[generate]   真实三级行业:        {has_industry_real} / {len(stock_list)}")
    print(f"[generate]   粗粒度行业:        {has_industry_coarse} / {len(stock_list)}")
    print(f"[generate]   跳过 (空/重):       {skipped}")
    print(f"[generate] 前 3: {stock_list[:3]}")
    print(f"[generate] 后 3: {stock_list[-3:]}")
    return 0


if __name__ == "__main__":
    sys.exit(generate())
