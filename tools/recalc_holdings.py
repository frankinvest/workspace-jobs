#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recalc_holdings.py — 由交易流水推算持仓（摊薄成本口径）

背景（Frank 2026-09-21 指出）：买卖会影响持仓成本，原来的 data/stock_holdings.json
只是「某一时刻的快照 + 手工填的成本」，成交之后成本不会跟着变，算出来的持仓盈亏就不对。

本脚本把 data/trades.json（期初持仓 + 每笔买卖）作为唯一数据源，按券商常用的
「摊薄成本」口径推算每只票的成本：

    净投入 = 期初股数×期初成本 + Σ买入股数×买入价 − Σ卖出股数×卖出价
    成本价 = 净投入 / 当前股数          （卖出价高于成本会拉低成本，低于成本会抬高成本）

输出写回 data/stock_holdings.json（前端只读这个文件，所以组件不用改）。

用法:
  python3 tools/recalc_holdings.py --dry-run   # 只看结果，不写文件
  python3 tools/recalc_holdings.py             # 写回 data/stock_holdings.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRADES = ROOT / "data" / "trades.json"
HOLDINGS = ROOT / "data" / "stock_holdings.json"


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def compute(trades_doc):
    """returns (positions, warnings) —— positions 顺序：期初顺序在前，新票按首次交易顺序追加"""
    order, name, shares, amount = [], {}, {}, {}

    for p in trades_doc.get("opening", {}).get("positions", []):
        code = p["code"]
        order.append(code)
        name[code] = p["name"]
        shares[code] = p["shares"]
        amount[code] = p["shares"] * p["cost"]

    for t in trades_doc.get("trades", []):
        code = t["code"]
        if code not in name:
            order.append(code)
            name[code] = t["name"]
            shares[code] = 0
            amount[code] = 0.0
        n, px = t["shares"], t["price"]
        if t["side"] == "buy":
            shares[code] += n
            amount[code] += n * px
        elif t["side"] == "sell":
            shares[code] -= n
            amount[code] -= n * px
        else:
            raise SystemExit(f"未知 side: {t}")

    positions, warnings = [], []
    for code in order:
        s, a = shares[code], amount[code]
        if s <= 0:
            # 清仓：记下已实现盈亏，不进持仓表
            warnings.append(f"{name[code]}({code}) 已清仓/股数<=0，未写入持仓；剩余净投入 {a:.2f} 元")
            continue
        positions.append({
            "code": code,
            "name": name[code],
            "shares": s,
            "cost": round(a / s, 3),
        })
    return positions, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    doc = load(TRADES)
    positions, warnings = compute(doc)

    old = {h["code"]: h for h in load(HOLDINGS)}
    print(f"{'code':<8}{'name':<16}{'shares':>10}{'cost':>12}   变化")
    for p in positions:
        o = old.get(p["code"])
        delta = ""
        if o is None:
            delta = "新增"
        elif o["shares"] != p["shares"] or abs(o["cost"] - p["cost"]) > 1e-9:
            delta = f"{o['shares']}@{o['cost']} → {p['shares']}@{p['cost']}"
        print(f"{p['code']:<8}{p['name']:<16}{p['shares']:>10}{p['cost']:>12}   {delta}")
    for w in warnings:
        print("⚠️ ", w)
    print(f"\n共 {len(positions)} 只（原 {len(old)} 只）")

    if args.dry_run:
        print("[dry-run] 未写文件")
        return 0
    with open(HOLDINGS, "w", encoding="utf-8") as fh:
        json.dump(positions, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"✅ 已写回 {HOLDINGS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
