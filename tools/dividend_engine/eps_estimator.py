# -*- coding: utf-8 -*-
"""
eps_estimator.py - 时序动态全年 EPS 外推引擎 (Jobs 重构版, 对齐《股息率估算.pdf》)

【2026-06-10 紧急救火 v2 — Frank 提示的 3 个事实性 bug 已修】
1. ❌ 路径错 (Frank 写 dividend_engine/, 实际 tools/dividend_engine/) → ✅ 修正
2. ❌ f-string `f"{last_year1231}"` 缺 `{}` 触发 NameError → ✅ 改为 `f"{last_year}1231"`
3. ❌ Frank 提供代码函数体缩进多一级 (8 空格 vs 4 空格) → ✅ 全部归 4 空格

【重构算法亮点 (保留 Frank 业务逻辑)】
- 全面斩断绝对值硬编码 (不再写死 Q4=0.30/A 类扣 0.05)
- A 类: 同比因子 yoy_factor, 边界防御 0.7-1.3, 2% 风险扣减
- B 类: 历史季节性贡献 × 0.85 折价 (比例制, 不用 0.30 地板价)
- C 类: 3 年滚动均值中枢, 权重比例平滑
- D 类: 通用兜底
"""
import pandas as pd


class EPSEstimator:
    @staticmethod
    def estimate_full_year_eps(hub, symbol: str, category: str, target_year: str = "2026") -> float:
        """动态评估剩余季度数据，测算前瞻性全年每股收益"""
        # 统一清洗类别字符串, 兼容 "A" 或 "A类"
        cat = str(category).upper().replace("类", "").strip()
        if cat not in ["A", "B", "C", "D"]:
            cat = "A"

        try:
            # 1. 捞取 80 季度深度财务摘要底座
            df_abstract = hub.fetch_financial_abstract(symbol)
            if df_abstract.empty or '指标' not in df_abstract.columns:
                return 1.5

            # 2. 精准正则定位每股收益特征行
            eps_row = df_abstract[df_abstract['指标'].str.contains('基本每股收益|每股收益', na=False)]
            if eps_row.empty:
                return 1.5

            # 3. 剥离文本列, 清洗出纯粹的报告期时间戳序列
            report_cols = [col for col in df_abstract.columns if col not in ['选项', '指标']]

            # 4. 历史锚点: 前一年全年的真实 EPS 基础分
            last_year = str(int(target_year) - 1)
            # === Frank bug #2 修复: f-string 缺 {} ===
            last_year_stamp = f"{last_year}1231"

            last_year_eps = 1.0
            if last_year_stamp in report_cols:
                try:
                    last_year_eps = float(eps_row[last_year_stamp].values[0])
                except Exception:
                    last_year_eps = 1.0

            # ========================================================
            # 🚀 策略 A: 目标年份年报已披露, 直接取实际交卷真值
            # ========================================================
            full_year_report_stamp = f"{target_year}1231"
            if full_year_report_stamp in report_cols:
                return round(float(eps_row[full_year_report_stamp].values[0]), 2)

            # ========================================================
            # 🚀 策略 B: 年份未过完, 启动符合《股息率估算.pdf》精髓的比例外推
            # ========================================================
            current_year_reported_stamps = sorted([col for col in report_cols if col.startswith(target_year)])

            # 情况 1: 目标年份处于极限真空期, 连一季报都没出
            if not current_year_reported_stamps:
                if cat == "A":
                    return round(last_year_eps * 0.98, 2)  # A类留 2% 确定性审慎安全余量
                elif cat == "B":
                    return round(last_year_eps * 0.90, 2)  # B类强周期初始打 9 折防变脸
                else:
                    return round(last_year_eps, 2)

            # 情况 2: 已有部分季度财报发布, 提取最新报告期既得真值
            latest_reported_stamp = current_year_reported_stamps[-1]
            reported_eps = float(eps_row[latest_reported_stamp].values[0])
            suffix = latest_reported_stamp[-4:]  # "0331" / "0630" / "0930"
            last_year_corresponding_stamp = f"{last_year}{suffix}"

            # --- 核心分类定量演算分支 ---

            # 【Class A · 业绩稳定类 (银行、电信、茅台)】
            # 核心: 按已披露进度的同比变化趋势年化外推 + 比例留存余量
            if cat == "A":
                yoy_factor = 1.0
                if last_year_corresponding_stamp in report_cols:
                    try:
                        last_year_comp_eps = float(eps_row[last_year_corresponding_stamp].values[0])
                        if last_year_comp_eps > 0:
                            yoy_factor = reported_eps / last_year_comp_eps
                    except Exception:
                        yoy_factor = 1.0

                # 动态变化率边界防御: 限制极端异动外推 (0.7-1.3 倍)
                yoy_factor = max(0.7, min(1.3, yoy_factor))
                final_eps = last_year_eps * yoy_factor
                # 对齐文档: 2% 抗风险扣减 (比例制, 不用绝对值)
                final_eps *= 0.98
                return round(final_eps, 2)

            # 【Class B · 业绩强周期类 (海运、有色、煤炭)】
            # 核心: 提取企业自身历史季节性贡献, 强计提周期折价
            elif cat == "B":
                last_year_comp_eps = 0.0
                if last_year_corresponding_stamp in report_cols:
                    try:
                        last_year_comp_eps = float(eps_row[last_year_corresponding_stamp].values[0])
                    except Exception:
                        last_year_comp_eps = 0.0

                # 去年未披露缺失季度的实际净贡献
                last_year_remaining_contribution = max(0.0, last_year_eps - last_year_comp_eps)
                # 剩余季度整体 × 0.85 (比例制, 不用 0.30 地板价)
                estimated_remaining_eps = last_year_remaining_contribution * 0.85
                final_eps = reported_eps + estimated_remaining_eps
                return round(final_eps, 2)

            # 【Class C · 业绩取决于中观预期类 (火电、水务、家电)】
            # 核心: 3 年滚动历史年报均值, 平滑周期波动
            elif cat == "C":
                historical_full_eps = []
                for i in range(1, 4):
                    y_stamp = f"{str(int(target_year) - i)}1231"
                    if y_stamp in report_cols:
                        try:
                            historical_full_eps.append(float(eps_row[y_stamp].values[0]))
                        except Exception:
                            pass

                # 3 年滚动均值 = 一致性预期替代中枢
                consensus_mid_eps = (
                    sum(historical_full_eps) / len(historical_full_eps)
                    if historical_full_eps
                    else last_year_eps
                )
                # 当前已披露节点的时间分布占比
                weight_ratio = 0.25 if suffix == "0331" else (0.50 if suffix == "0630" else 0.75)
                estimated_remaining_eps = consensus_mid_eps * (1.0 - weight_ratio)
                final_eps = reported_eps + estimated_remaining_eps
                return round(final_eps, 2)

            # 【Class D · 兜底】通用比例外推
            else:
                weight_ratio = 0.25 if suffix == "0331" else (0.50 if suffix == "0630" else 0.75)
                return round(reported_eps + last_year_eps * (1.0 - weight_ratio), 2)

        except Exception:
            return 1.5
