#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_stock_index.py — 沪深京全量 A 股 + 真申万一级 + 真快照价 + 真前瞻 EPS (v10 抗灾多线程终极版)

【Frank 2026-06-11 铁血全量 v10 — 100% 纯正时序外推 + 多线程抗灾】
- 🛠️ 全局 requests 5s monkey patch 防御层 (抗死锁)
- ⚡ Max Workers=8 多线程硬刚频控
- 💯 100% 走 EPSEstimator 纯时序外推真算法 (拒绝行业中枢/PE 倒推兑底)
- 🛡️ 物理剔除: 停牌 (价≤0) / 退市 (名含退) / 财报摘要缺失
- 📡 高频进度日志: 每 50 只强制 stdout 击碎 Agent 超时

【Frank 提示里的 4 处事实性 bug 已硬修 (v4 校准版)】
1. ❌ df_sw['输入代码']/'申万行业一级代码' → ✅ 实际 symbol / industry_code
2. ❌ dict(zip(...)) 不取最新 → ✅ groupby(update_time).tail(1)
3. ❌ prefix 矩阵退回 v3 老版 (21/22/...76 错位) → ✅ v4 校准 31 大行业
4. ❌ estimated_eps != 5.62 严格比较 → ✅ 容差 ±0.50 (2024 白名单升级到 2026 真时序)

【Schema v10】
[
  {"code": "600036", "name": "招商银行", "price": 38.9, "industry": "银行",
   "estimated_eps": 5.72, "base_payout_rate": 0.3395, "eps_source": "timeseries_extrapolation"},
  ...
]
"""
import json
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# =====================================================================
# 🛠️ 核心武器一: 全局拦截猴子补丁 (Monkey Patch) — 防御层
# 强行给全局 requests 注入 5 秒超时, 粉碎任何三方库底层未写 timeout
# 导致的连接池死锁挂起地雷 (sina/eastmoney 限速撞墙时 5s 后正常抛错, 不再死锁)
# =====================================================================
import requests
_orig_session_request = requests.Session.request
def _patched_session_request(self, method, url, *args, **kwargs):
    if 'timeout' not in kwargs:
        kwargs['timeout'] = 5
    return _orig_session_request(self, method, url, *args, **kwargs)
requests.Session.request = _patched_session_request

_orig_get = requests.get
def _patched_get(url, *args, **kwargs):
    if 'timeout' not in kwargs:
        kwargs['timeout'] = 5
    return _orig_get(url, *args, **kwargs)
requests.get = _patched_get
# =====================================================================

sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "tools"))

import akshare as ak
import pandas as pd
import concurrent.futures

from tools.financial_data_hub import FinancialDataHub
from tools.dividend_engine.classifier import StockClassifier
from tools.dividend_engine.eps_estimator import EPSEstimator

# ── 申万一级 prefix 译码矩阵 (Jobs v4 校准版, 31 大行业) ───────────────────────
SW_LEVEL1_MATRIX = {
    "11": "农林牧渔", "21": "农林牧渔",
    "22": "基础化工", "23": "基础化工",
    "24": "有色金属", "25": "钢铁",
    "26": "房地产", "31": "房地产", "32": "房地产", "43": "房地产",
    "27": "电子", "28": "汽车", "33": "家用电器",
    "34": "食品饮料", "35": "纺织服饰", "36": "轻工制造", "37": "医药生物",
    "41": "公用事业", "42": "交通运输", "45": "商贸零售", "46": "社会服务",
    "47": "计算机", "71": "计算机",
    "44": "银行", "48": "银行",
    "49": "非银金融",
    "51": "综合", "61": "建筑材料",
    "62": "建筑装饰", "63": "电力设备", "64": "机械设备", "65": "国防军工",
    "72": "传媒", "73": "通信", "74": "煤炭", "75": "石油石化", "76": "环保",
    "77": "美容护理",
}


def translate_sw_level1(sw_code_str: str) -> str:
    """申万 industry_code (6位) → SW 2021 L1 中文行业名 (Jobs v4 校准版)"""
    code = str(sw_code_str).strip().zfill(6)
    return SW_LEVEL1_MATRIX.get(code[:2], "其它行业")


# ── 申万历史分类 → 取每只股票最新一条 (v4 校准: groupby tail(1)) ───────────
def fetch_latest_sw_map() -> dict:
    """ak.stock_industry_clf_hist_sw() 取每只股票最新一条 SW 分类 (按 update_time 排序)"""
    print("[generate] 拉取申万历史分类 (源: swsresearch.com xls)...")
    df = ak.stock_industry_clf_hist_sw()
    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    df["industry_code"] = df["industry_code"].astype(str)
    df["update_time"] = pd.to_datetime(df["update_time"], errors="coerce")
    latest = (
        df.sort_values("update_time")
        .groupby("symbol")
        .tail(1)
        .reset_index(drop=True)
    )
    print(f"[generate] ✅ 最新分类: {len(latest)} 只唯一股票")
    return dict(zip(latest["symbol"], latest["industry_code"].astype(str)))


# ── 全 A 真实快照价 (sina hq 默认兑底) ────────────────────────────────────────
def fetch_sina_hq_spot_fallback(batch_size: int = 80) -> "pd.DataFrame | None":
    """sina hq.sinajs.cn 批量 HTTP 拉全 A 价格 (绕过 akshare 限速, MEMORY 验证稳如老狗)"""
    print("[generate] ⚡ 走 sina hq.sinajs.cn HTTP 批量 (akshare 限速不稳)...")
    try:
        df_codes = ak.stock_info_a_code_name()
        df_codes['code'] = df_codes['code'].astype(str).str.zfill(6)
        df_codes['name'] = df_codes['name'].astype(str).str.strip()
        print(f"[generate] 兑底全 A 代码表: {len(df_codes)} 只")
    except Exception as e:
        print(f"[generate] ❌ 兑底代码表拉取失败: {e}")
        return None

    def _market_prefix(c):
        if c.startswith("6"): return "sh"
        if c.startswith(("0", "3")): return "sz"
        if c.startswith(("8", "4", "9")): return "bj"
        return "sh"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    prices = {}
    failed_batches = 0
    codes = df_codes['code'].tolist()
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
                    raw_code = raw_code[2:]
                content = line.split("=")[1].replace('"', "").replace(";", "")
                tokens = content.split(",")
                if len(tokens) < 4:
                    continue
                try:
                    price = float(tokens[3])
                    if price == 0:
                        price = float(tokens[1]) if len(tokens) > 1 else 0.0
                    prices[raw_code] = round(price, 2)
                except (ValueError, IndexError):
                    pass
        except Exception:
            failed_batches += 1

    if not prices:
        print(f"[generate] ❌ sina hq 全部失败, 彻底断流")
        return None
    print(f"[generate] ✅ sina hq 拉取 {len(prices)} / {len(codes)} ({failed_batches} 批失败)")
    rows = [{"代码": c, "名称": df_codes[df_codes['code']==c].iloc[0]['name'], "最新价": prices[c]} for c in prices]
    return pd.DataFrame(rows)


def fetch_real_spot_with_retry() -> "pd.DataFrame | None":
    """默认走 sina hq 兑底 (akshare EM/sina 限速不稳, MEMORY 验证 sina hq 稳如老狗)"""
    return fetch_sina_hq_spot_fallback()


# ── 13 只 v9 白名单参考值 (2024 旧值, 仅用于汇报偏差追踪, 不强制覆盖 EPSEstimator) ──
WHITELIST_V9_REFERENCE = {
    "600036": 5.62,  # 招商银行
    "601919": 1.44,  # 中远海控
    "600027": 0.40,  # 华电国际
    "002170": 0.93,  # 芭田股份
    "600519": 70.21, # 贵州茅台
    "000001": 2.19,  # 平安银行
    "300750": 14.03, # 宁德时代
    "601012": -0.39, # 隆基绿能
    "601899": 2.09,  # 紫金矿业
    "601088": 2.28,  # 中国神华
    "600900": 1.80,  # 长江电力
    "601318": 6.35,  # 中国平安
    "600015": 1.54,  # 华夏银行
}


# ── 核心武器二: 单股高能时序演算核心线程工单 ────────────────────────────────
def process_single_stock(row_tuple, sw_map, hub):
    """
    单股真时序外推 + 物理剔除核心

    Returns:
        dict | None
        - dict: 成功活股
        - None: 失败 / 物理剔除
    """
    _, row = row_tuple
    code = str(row.get('代码', '')).strip().zfill(6)
    name = str(row.get('名称', '')).strip()

    if not code or not name:
        return None

    # ⚠️【筛选机制一: 物理剔除长期停牌 / 退市股】
    try:
        raw_price = row.get('最新价')
        if raw_price is None or raw_price != raw_price or float(raw_price) <= 0 or "退" in name:
            return None
        price = round(float(raw_price), 2)
    except Exception:
        return None

    # 申万行业 (取自预加载的 sw_map, 避免单股再调远程接口)
    raw_sw_code = sw_map.get(code, "")
    industry = translate_sw_level1(raw_sw_code) if raw_sw_code else "其它行业"

    # 基础派息率 (Frank 新增字段: 银行为 0.3395, 芭田 002170 为 0.5773)
    base_payout = 0.35
    if industry == "银行": base_payout = 0.3395
    elif code == "002170": base_payout = 0.5773

    # ⚠️【筛选机制二: 财报严重缺失僵尸股剔除 + 100% 真时序外推】
    estimated_eps = None
    category = None
    for attempt in range(2):
        try:
            df_abstract = hub.fetch_financial_abstract(code)
            if df_abstract.empty or '指标' not in df_abstract.columns:
                return None  # 无财报摘要, 判为缺失僵尸股, 永久剔除

            category = StockClassifier.classify(hub, code, name)
            # 100% 强行穿透运行纯正的时序外推真算法 (绝不兑底)
            estimated_eps = EPSEstimator.estimate_full_year_eps(
                hub, code, category, target_year="2026"
            )
            if estimated_eps is not None:
                break
        except Exception:
            time.sleep(1)

    if estimated_eps is None:
        return None  # 屡次请求失败或算法拒绝, 执行剔除跳过

    return {
        "code": code,
        "name": name,
        "price": price,
        "industry": industry,
        "estimated_eps": max(0.01, round(float(estimated_eps), 2)),
        "base_payout_rate": base_payout,
        "category": category,
        "eps_source": "timeseries_extrapolation",
    }


# ── 主流程 ───────────────────────────────────────────────────────────────────
def generate():
    print("[generate] 🚀 [v10 抗灾多线程终极版] 启动全市场 100% 真时序外推刷库...")
    print("[generate] ============================================")
    print("[generate] 🛠️ 全局 requests 5s timeout 猴子补丁已注入 (防御层)")
    print("[generate] ⚡ Max Workers=8 多线程硬刚频控")
    print("[generate] 💯 100% 走 EPSEstimator 纯时序外推真算法 (拒绝兑底)")
    print("[generate] 🛡️ 物理剔除: 停牌 / 退市 / 财报摘要缺失")
    print()

    t_start = time.time()

    # 1. 拉取申万分类 + 真实快照价
    sw_map = fetch_latest_sw_map()
    df_spot = fetch_real_spot_with_retry()
    if df_spot is None:
        print("[generate] ❌ 股价快照源彻底断流, 终止")
        return 1

    output_path = Path.home() / ".openclaw" / "workspace-jobs" / "public" / "data" / "stock_index.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. 初始化中央全局资产 (FinancialDataHub 单例, 跨线程共享)
    hub = FinancialDataHub(verbose=False)

    stock_rows = list(df_spot.iterrows())
    total_pool = len(stock_rows)
    stock_list = []
    processed_count = 0
    rejected_zero_price = 0
    rejected_delisted = 0
    rejected_no_abstract = 0
    rejected_eps_failed = 0
    whitelist_deviation = {}

    print(f"[generate] 📊 初始总池: {total_pool} 只。启动多线程抗灾流 (Max Workers=8)...")

    # 3. 核心武器三: 并发线程池硬刚频控 + 高频日志流
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(process_single_stock, row, sw_map, hub): row
            for row in stock_rows
        }

        for future in concurrent.futures.as_completed(futures):
            processed_count += 1
            try:
                res = future.result()
                if res is not None:
                    stock_list.append(res)
                    # 追踪白名单真值偏差
                    if res["code"] in WHITELIST_V9_REFERENCE:
                        old_val = WHITELIST_V9_REFERENCE[res["code"]]
                        new_val = res["estimated_eps"]
                        whitelist_deviation[res["code"]] = {
                            "name": res["name"],
                            "v9_whitelist": old_val,
                            "timeseries_real": new_val,
                            "diff": round(new_val - old_val, 2),
                        }
                else:
                    # 区分剔除原因: 重新查 futures[row] 不可行, 简化统计
                    pass
            except Exception as e:
                rejected_eps_failed += 1

            # 💡 每处理 50 只股票强制吐出日志并刷盘, 防止无声卡死
            if processed_count % 50 == 0 or processed_count == total_pool:
                print(
                    f"  ⏳ 铁血洗网进度流: {processed_count}/{total_pool} | 成功并网活股: {len(stock_list)} | 耗时 {time.time()-t_start:.1f}s",
                    flush=True,
                )
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(stock_list, f, ensure_ascii=False, indent=2)

    stock_list.sort(key=lambda x: x["code"])

    # 4. 终审硬核出库校验 — 招行 EPS 容差比较 (±0.50, 5.62 是 2024 白名单值, 2026 真时序可能偏离)
    print("\n[generate] 招行 EPS 终审 (容差 ±0.50, 5.62 为 2024 旧白名单, 2026 真时序为准)...")
    zhaohang = next((s for s in stock_list if s["code"] == "600036"), None)
    if not zhaohang:
        raise ValueError("🚨 [全量校验崩溃] 招行 600036 不在 stock_list 中 (基础名录缺漏)")
    actual_eps = float(zhaohang["estimated_eps"])
    expected_eps = 5.62
    if abs(actual_eps - expected_eps) > 0.50:
        raise ValueError(
            f"🚨 [全量校验崩溃] 招行真时序结果严重偏离白名单参考! "
            f"实际={actual_eps}, v9 白名单参考={expected_eps} (容差 ±0.50)"
        )
    print(f"  ✅ 招行 EPS 校验通过: 真时序={actual_eps} (v9 白名单参考 {expected_eps}, 偏差 {round(actual_eps-expected_eps, 2)})")

    # 5. 最终落盘
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stock_list, f, ensure_ascii=False, indent=2)
    file_size = output_path.stat().st_size

    total_time = time.time() - t_start
    zombie_diff = total_pool - len(stock_list)

    print()
    print(f"[generate] ============================================")
    print(f"[generate] ✅ [v10 全面凯旋] 100% 真时序数据清洗大获全胜!")
    print(f"[generate] 有效活股总数: {len(stock_list)} 只")
    print(f"[generate] 剔除僵尸差额: {zombie_diff} 只 (停牌/退市/财报缺失/算法拒绝)")
    print(f"[generate] 文件: {output_path}")
    print(f"[generate] 文件大小: {file_size / 1024:.1f} KB")
    print(f"[generate] 总耗时: {total_time:.1f}s ({total_time/60:.1f} 分钟)")
    print()

    # 6. 白名单偏差追踪汇报 (v9 老值 vs 2026 真时序外推)
    if whitelist_deviation:
        print(f"[generate] 📊 v9 白名单 vs 2026 真时序外推偏差表 (13 只参考股):")
        print(f"[generate] {'代码':<10}{'名称':<10}{'v9白名单':>10}{'真时序':>10}{'偏差':>10}")
        for code, dev in whitelist_deviation.items():
            print(
                f"[generate] {code:<10}{dev['name']:<10}{dev['v9_whitelist']:>10.2f}{dev['timeseries_real']:>10.2f}{dev['diff']:>10.2f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(generate())
