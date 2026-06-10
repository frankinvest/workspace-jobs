#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_stock_index.py — 沪深京全量 A 股 + 真申万一级 + 真实快照价 静态字典生成器 (v4)

【Frank 2026-06-10 终极架构 v4 — 静态数据真通电】
- 申万行业: ak.stock_industry_clf_hist_sw() 取每只股票【最新一条】+ Jobs 校准版 prefix 矩阵
- 真实价格: ak.stock_zh_a_spot() 新浪全市场快照 (3 次指数退避重试)
- 兜底价格: 15.0 (仅在拉取失败/停牌时使用, 全市场 < 0.5% 触发)

【Schema v4】
[
  {"code": "600036", "name": "招商银行", "price": 38.45, "industry": "银行"},
  ...
]

【数据源】
- 股票列表 + 价格: ak.stock_zh_a_spot() (sina, 5525 行, ~22s)
- SW 分类: ak.stock_industry_clf_hist_sw() (swsresearch.com xls, 12790 行历史 → 5872 最新)

【已知坑已修复 (v3 → v4 演进)】
- ❌ Frank 提示里的 '输入代码' / '申万行业一级代码' 列名 → ✅ 实际 symbol / industry_code
- ❌ dict(zip(...)) 取首次=2015 年老分类 → ✅ sort_values(update_time) + groupby tail(1)
- ❌ prefix 矩阵 5 处错位 (24/25/63/74/75) + 1 处 (61) → ✅ Jobs 校准版 31 大行业
- ❌ 8 个 prefix 缺漏 (11/26/31/32/44/47/51/77) → ✅ 全部补全

【硬断言 (v4 强化)】
- 12 只明星股行业归类 (与 v3 同步)
- 新增 招行/茅台 价格必须 != 15.0 兜底 (Frank v4 新要求)
"""
import json
import os
import sys
import time
from pathlib import Path

import akshare as ak
import pandas as pd
import requests


# ── 申万一级 prefix 译码矩阵 (Jobs 2026-06-10 校准版, v3 继承) ───────────────
SW_LEVEL1_MATRIX = {
    # 农林牧渔 (含历史老 prefix 11)
    "11": "农林牧渔",
    "21": "农林牧渔",
    # 基础化工 (Frank 矩阵误把 22 标为"煤炭/石油石化", 实际是基础化工)
    "22": "基础化工",
    "23": "基础化工",
    # 钢铁 / 有色金属 (Frank 矩阵 24/25 反了)
    "24": "有色金属",
    "25": "钢铁",
    # 房地产 (边缘 prefix)
    "26": "房地产",
    "31": "房地产",
    "32": "房地产",
    "43": "房地产",
    # 电子
    "27": "电子",
    # 汽车
    "28": "汽车",
    # 家用电器
    "33": "家用电器",
    # 食品饮料
    "34": "食品饮料",
    # 纺织服饰
    "35": "纺织服饰",
    # 轻工制造
    "36": "轻工制造",
    # 医药生物
    "37": "医药生物",
    # 公用事业
    "41": "公用事业",
    # 交通运输
    "42": "交通运输",
    # 商贸零售
    "45": "商贸零售",
    # 社会服务
    "46": "社会服务",
    # 计算机 (含边缘 prefix 47)
    "47": "计算机",
    "71": "计算机",
    # 银行 (含 SW 2014 老 prefix 44 和 SW 2021 新 prefix 48)
    "44": "银行",
    "48": "银行",
    # 非银金融
    "49": "非银金融",
    # 综合 (含边缘 prefix 51, 61 改为建筑材料)
    "51": "综合",
    "61": "建筑材料",  # 海螺水泥/东方雨虹/坚朗五金 全部 61xxxx
    # 建筑装饰
    "62": "建筑装饰",
    # 电力设备 (Frank 错"建筑材料", CATL 630701 是电力设备)
    "63": "电力设备",
    # 机械设备
    "64": "机械设备",
    # 国防军工
    "65": "国防军工",
    # 传媒
    "72": "传媒",
    # 通信
    "73": "通信",
    # 煤炭 (Frank 错"电力设备", 神华 740101 是煤炭)
    "74": "煤炭",
    # 石油石化 (Frank 错"美容护理", 中石化 750301 是石油石化)
    "75": "石油石化",
    # 环保
    "76": "环保",
    # 美容护理 (Frank 缺漏 prefix, 珀莱雅 770202 是美容护理)
    "77": "美容护理",
}


def translate_sw_level1(sw_code_str: str) -> str:
    """申万 industry_code (6位字符串) → SW 2021 Level 1 中文行业名 (Jobs 校准版)"""
    code = str(sw_code_str).strip().zfill(6)
    return SW_LEVEL1_MATRIX.get(code[:2], "其它行业")


# ── 申万历史分类 → 最新一条 (修复 dict 取老分类 bug) ─────────────────────────
def fetch_latest_sw_map() -> dict:
    """从 ak.stock_industry_clf_hist_sw() 取每只股票【最新一条】SW 分类

    Returns:
        dict: {stock_code_6digit: industry_code_6digit_str}
    """
    print("[generate] 拉取申万历史分类 (源: swsresearch.com StockClassifyUse_stock.xls)...")
    t0 = time.time()
    df = ak.stock_industry_clf_hist_sw()
    print(f"[generate] ✅ 原始 {len(df)} 行, 耗时 {time.time() - t0:.1f}s")

    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    df["industry_code"] = df["industry_code"].astype(str)
    df["update_time"] = pd.to_datetime(df["update_time"], errors="coerce")

    # 关键修复: 按 update_time 排序后 groupby tail(1) → 5872 只最新分类
    latest = (
        df.sort_values("update_time")
        .groupby("symbol")
        .tail(1)
        .reset_index(drop=True)
    )
    print(f"[generate] 最新分类: {len(latest)} 只唯一股票")
    return dict(zip(latest["symbol"], latest["industry_code"].astype(str)))


# ── 全 A 真实快照价 (akshare 主路径 + sina hq HTTP 兑底, Frank v4 核心要求) ───
def fetch_real_spot_with_retry(max_attempts: int = 5) -> "pd.DataFrame | None":
    """ak.stock_zh_a_spot() 新浪全 A 实时快照, 失败指数退避 2/4/8/16/32s 重试

    经验: sina 对单一 IP 有限速, akshare 封装的 stock_zh_a_spot() 会返 <html 限速页
    Fallback: 1次不走 akshare, 走 sina hq.sinajs.cn 批量 HTTP 拉 (0.05s 响应, 稳如老狗)

    Returns:
        pd.DataFrame | None: 包含列 ['代码', '名称', '最新价', ...] 的全 A 快照
    """
    print("[generate] ⚡ 拉取全 A 真实快照价 (ak.stock_zh_a_spot 新浪主路径)...")
    for attempt in range(1, max_attempts + 1):
        t0 = time.time()
        try:
            df = ak.stock_zh_a_spot()
            if df is not None and not df.empty:
                print(f"[generate] ✅ ak.stock_zh_a_spot 第 {attempt} 次拉取成功: {len(df)} 行, 耗时 {time.time() - t0:.1f}s")
                return df
            else:
                print(f"[generate] ⚠️ 第 {attempt} 次返回空 DataFrame")
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)[:100]}"
            print(f"[generate] ⚠️ ak.stock_zh_a_spot 第 {attempt} 次失败: {err_msg}")

        if attempt < max_attempts:
            wait = 2 ** attempt  # 2, 4, 8, 16
            print(f"[generate] 退避 {wait}s 后重试...")
            time.sleep(wait)

    # 兑底: 1次不走 akshare, 走 sina hq.sinajs.cn 批量 HTTP 拉
    print(f"[generate] ⚠️ akshare 主路径 {max_attempts} 次拉取全部失败, 尝试 sina hq.sinajs.cn HTTP 兑底...")
    return fetch_sina_hq_spot_fallback()


def fetch_sina_hq_spot_fallback(batch_size: int = 80) -> "pd.DataFrame | None":
    """sina hq.sinajs.cn 批量 HTTP 拉全 A 价格 (0.05s/批, 不走 akshare)

    先用 ak.stock_info_a_code_name() 拿代码表, 再逐批拉 hq.sinajs.cn
    返回 schema 对齐 ak.stock_zh_a_spot(): ['代码', '名称', '最新价', '时间戳']
    """
    print("[generate] ⚡ 走 sina hq.sinajs.cn HTTP 批量兑底 (绕过 akshare 限速)...")

    # 1. 拿全 A 代码表
    try:
        df_codes = ak.stock_info_a_code_name()
        df_codes['code'] = df_codes['code'].astype(str).str.zfill(6)
        df_codes['name'] = df_codes['name'].astype(str).str.strip()
        print(f"[generate] 兑底全 A 代码表: {len(df_codes)} 只")
    except Exception as e:
        print(f"[generate] ❌ 兑底代码表拉取失败: {e}")
        return None

    # 2. 构建 sina hq URL
    def _market_prefix(c: str) -> str:
        if c.startswith("6"):
            return "sh"
        if c.startswith(("0", "3")):
            return "sz"
        if c.startswith(("8", "4", "9")):
            return "bj"
        return "sh"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }

    # 3. 逐批拉价格
    prices = {}
    codes = df_codes['code'].tolist()
    failed_batches = 0
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        url = "https://hq.sinajs.cn/list=" + ",".join(f"{_market_prefix(c)}{c}" for c in batch)
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code != 200:
                failed_batches += 1
                continue
            for line in r.text.split("\n"):
                if "=" not in line:
                    continue
                raw_code = line.split("=")[0].split("_")[-1]
                if len(raw_code) > 6:
                    raw_code = raw_code[2:]  # 去掉 sh/sz/bj 前缀
                content = line.split("=")[1].replace('"', "").replace(";", "")
                tokens = content.split(",")
                if len(tokens) < 4:
                    continue
                try:
                    # sina hq 字段: 0名称, 1今开, 2昨收, 3现价, 4日高, 5日低, 6竞买, 7竞卖, ...
                    price = float(tokens[3])
                    if price == 0:
                        price = float(tokens[1]) if len(tokens) > 1 else 0.0
                    prices[raw_code] = round(price, 2)
                except (ValueError, IndexError):
                    pass
        except Exception as e:
            failed_batches += 1
            print(f"[generate]  batch {i} 异常: {type(e).__name__}: {str(e)[:60]}")

    if not prices:
        print(f"[generate] ❌ sina hq 全部 {failed_batches} 批失败, 彻底断流")
        return None

    print(f"[generate] ✅ sina hq 拉取 {len(prices)} / {len(codes)} 只价格 ({failed_batches} 批失败)")

    # 4. 构建与 ak.stock_zh_a_spot 兼容的 DataFrame
    rows = []
    for _, r in df_codes.iterrows():
        code = r['code']
        if code in prices:
            rows.append({
                "代码": code,
                "名称": r['name'],
                "最新价": prices[code],
            })
    df_out = pd.DataFrame(rows)
    if df_out.empty:
        return None
    return df_out


# ── 12 只明星股硬断言 (含 Frank v4 新增价格断言) ──────────────────────────────
def assert_canonical_industries_and_prices(stock_list: list) -> None:
    """12 只明星股硬断言 (v4 强化版, 加价格 != 15.0 兜底校验)

    Raises:
        ValueError: 任何一只行业归类错位 或 招行/茅台价格 == 15.0 兜底
    """
    expected = {
        # 银行 (3 只) - 招行/兴业/工商
        "600036": ("银行", ["招商银行", "招行"]),
        "601166": ("银行", ["兴业银行"]),
        "601398": ("银行", ["工商银行", "工行"]),
        # 非银金融
        "601318": ("非银金融", ["中国平", "中国平安"]),
        # 食品饮料 - 贵州茅台 (Frank 价格断言重点)
        "600519": ("食品饮料", ["贵州茅台", "茅台"]),
        # 汽车
        "002594": ("汽车", ["比亚迪"]),
        # 公用事业
        "600900": ("公用事业", ["长江电力"]),
        # 医药生物
        "600276": ("医药生物", ["恒瑞医药", "恒瑞"]),
        # 电力设备 (Frank 矩阵错位修正点)
        "300750": ("电力设备", ["宁德时代", "宁德"]),
        "601012": ("电力设备", ["隆基绿能", "隆基"]),
        # 有色金属 (Frank 矩阵错位修正点)
        "601899": ("有色金属", ["紫金矿业", "紫金"]),
        # 煤炭 (Frank 矩阵错位修正点)
        "601088": ("煤炭", ["中国神华", "神华"]),
        # 石油石化 (Frank 矩阵错位修正点)
        "600028": ("石油石化", ["中国石化", "中石化"]),
    }
    by_code = {s["code"]: s for s in stock_list}
    failures = []

    for code, (expect_industry, name_keywords) in expected.items():
        s = by_code.get(code)
        if s is None:
            failures.append(f"  ❌ {code}: 不在 stock_list 中 (基础名录缺漏)")
            continue
        actual_name = s["name"]
        actual_industry = s["industry"]
        name_ok = any(kw in actual_name for kw in name_keywords)
        industry_ok = (actual_industry == expect_industry)
        if not (name_ok and industry_ok):
            msg = f"  ❌ {code} {actual_name}: 行业={actual_industry!r} (期望 {expect_industry!r})"
            if not name_ok:
                msg += f", 名称={actual_name!r} (期望含 {name_keywords!r})"
            failures.append(msg)
        else:
            price_str = f"@{s['price']:.2f}" if s["price"] > 0 else "@STOPPED"
            print(f"  ✅ {code} {actual_name} → {actual_industry} {price_str}")

    # Frank v4 新增: 招行 + 茅台 价格必须脱离 15.0 兜底 (证明快照源生效)
    for hero_code, hero_name in [("600036", "招商银行"), ("600519", "贵州茅台")]:
        s = by_code.get(hero_code)
        if s and s["price"] == 15.0:
            failures.append(
                f"  ❌ {hero_code} {s['name']}: 价格仍被困在 15.0 元兜底, "
                f"未成功捕获 ak.stock_zh_a_spot() 快照!"
            )

    if failures:
        print()
        print("🚨 [正本清源失败] 12 只明星股行业/价格校验未通过:")
        for f in failures:
            print(f)
        raise ValueError(
            f"🚨 [正本清源失败] {len(failures)} 处错误 (行业归类/价格兜底)! "
            f"请检查 prefix 矩阵 + 真实价抓取逻辑"
        )
    print(f"\n[generate] ✅ 12 只明星股行业归类 + 招行/茅台价格 (非 15.0 兜底) 全部校验通过")


# ── 主流程 ───────────────────────────────────────────────────────────────────
def generate():
    print("[generate] 启动沪深京全量 A 股 + 真申万一级 + 真实快照价 静态库生成 (v4)")
    print("[generate] ============================================")
    print("[generate] 数据源:")
    print("[generate]   - 股票列表 + 价格: ak.stock_zh_a_spot() (sina, 3 次重试)")
    print("[generate]   - SW 行业分类: ak.stock_industry_clf_hist_sw() (swsresearch.com xls)")
    print("[generate]   - 行业译码: Jobs 校准版 prefix 矩阵 (31 大行业数据驱动)")
    print("[generate]   - 价格兜底: 15.0 (仅快照源失败的停牌/异常股)")
    print()

    # 1. SW 行业分类
    sw_map = fetch_latest_sw_map()

    # 2. 真价格快照 (3 次指数退避)
    df = fetch_real_spot_with_retry(max_attempts=3)
    if df is None:
        print("[generate] ❌ 股价快照源彻底断流, 终止 (拒绝用 15.0 兜底全市场)")
        return 1

    # 3. 适配列名 + 清洗落库
    stock_list = []
    no_price_count = 0
    no_industry_count = 0
    for _, row in df.iterrows():
        code = str(row.get("代码", "")).strip().zfill(6)
        name = str(row.get("名称", "")).strip()
        if not code or not name:
            continue

        # 价格清洗: 优先真价, 失败 fallback 15.0
        try:
            raw_price = row.get("最新价", 0.0)
            if raw_price != raw_price or raw_price is None:  # NaN 检测
                price = 15.0
                no_price_count += 1
            else:
                price = round(float(raw_price), 2)
                if price == 0.0:  # 停牌
                    price = 15.0
                    no_price_count += 1
        except (TypeError, ValueError, Exception):
            price = 15.0
            no_price_count += 1

        # 行业清洗: SW 分类 → 一级行业名
        raw_sw_code = sw_map.get(code, "")
        if raw_sw_code:
            industry = translate_sw_level1(raw_sw_code)
        else:
            industry = "未分类"
            no_industry_count += 1

        stock_list.append({
            "code": code,
            "name": name,
            "price": price,
            "industry": industry,
        })

    # 按代码升序排序
    stock_list.sort(key=lambda x: x["code"])

    # 4. 12 只明星股硬断言 (含 Frank 价格断言)
    print("\n[generate] 12 只明星股硬断言 (含 Frank v4 价格 != 15.0 兜底校验)...")
    assert_canonical_industries_and_prices(stock_list)

    # 5. 落盘
    output_path = Path.home() / ".openclaw" / "workspace-jobs" / "public" / "data" / "stock_index.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stock_list, f, ensure_ascii=False, indent=2)
    file_size = output_path.stat().st_size

    # 6. 统计
    industry_dist = {}
    for s in stock_list:
        ind = s["industry"]
        industry_dist[ind] = industry_dist.get(ind, 0) + 1
    has_real_price = sum(1 for s in stock_list if s["price"] != 15.0)
    has_fallback_15 = sum(1 for s in stock_list if s["price"] == 15.0)

    zhaohang = next(s for s in stock_list if s["code"] == "600036")
    maotai = next(s for s in stock_list if s["code"] == "600519")

    print()
    print(f"[generate] ============================================")
    print(f"[generate] ✅ [大获全胜] 成功导出 {len(stock_list)} 只股票至 {output_path}")
    print(f"[generate] 文件大小: {file_size / 1024:.1f} KB")
    print(f"[generate] 价格统计:")
    print(f"[generate]   真实快照价: {has_real_price} / {len(stock_list)} ({has_real_price/len(stock_list)*100:.1f}%)")
    print(f"[generate]   15.0 兜底:  {has_fallback_15} / {len(stock_list)} ({has_fallback_15/len(stock_list)*100:.1f}%) - 停牌/无数据")
    print(f"[generate] 行业统计: {len(industry_dist)} 个 SW 2021 L1 行业")
    for ind in sorted(industry_dist.keys(), key=lambda x: -industry_dist[x]):
        print(f"[generate]   {ind:<10} {industry_dist[ind]:>4} 只")
    print(f"[generate] 无 SW 分类: {no_industry_count} 只 (新上市/北交所)")
    print()
    print(f"[generate] 🎯 招行 (600036): 价格 {zhaohang['price']:.2f} 元  行业 {zhaohang['industry']}")
    print(f"[generate] 🎯 茅台 (600519): 价格 {maotai['price']:.2f} 元  行业 {maotai['industry']}")
    return 0


if __name__ == "__main__":
    sys.exit(generate())
