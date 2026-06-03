# -*- coding: utf-8 -*-
"""
eps_estimator.py - 时序动态全年 EPS 外推引擎
"""
import pandas as pd


class EPSEstimator:
    @staticmethod
    def estimate_full_year_eps(hub, symbol: str, category: str, target_year: str = "2026") -> float:
        """动态评估剩余季度数据，测算前瞻性全年每股收益"""
        try:
            df_abstract = hub.fetch_financial_abstract(symbol)
            if df_abstract.empty or '指标' not in df_abstract.columns:
                return 1.5

            eps_row = df_abstract[df_abstract['指标'].str.contains('基本每股收益|每股收益', na=False)]
            if eps_row.empty:
                return 1.5

            report_cols = [col for col in df_abstract.columns if col not in ['选项', '指标']]

            # 策略 A：年报已披露，直接取实际值
            full_year_report_stamp = f"{target_year}1231"
            if full_year_report_stamp in report_cols:
                return round(float(eps_row[full_year_report_stamp].values[0]), 2)

            # 策略 B：年份未过完，启动时序外推
            current_year_reported_stamps = sorted([col for col in report_cols if col.startswith(target_year)])
            last_year_stamp = f"{str(int(target_year) - 1)}1231"
            last_year_eps = 1.0
            if last_year_stamp in report_cols:
                last_year_eps = float(eps_row[last_year_stamp].values[0])

            # 目标年份连一季报都没出
            if not current_year_reported_stamps:
                return round(last_year_eps - 0.05, 2) if category == "A" else round(last_year_eps, 2)

            latest_reported_stamp = current_year_reported_stamps[-1]
            reported_eps = float(eps_row[latest_reported_stamp].values[0])

            if latest_reported_stamp.endswith("0930"):
                missing_quarters = ["Q4"]
            elif latest_reported_stamp.endswith("0630"):
                missing_quarters = ["Q3", "Q4"]
            elif latest_reported_stamp.endswith("0331"):
                missing_quarters = ["Q2", "Q3", "Q4"]
            else:
                missing_quarters = []

            estimated_remaining_eps = 0.0
            for q in missing_quarters:
                if category == "B" and q == "Q4":
                    estimated_remaining_eps += 0.30  # B类周期股Q4淡季0.30地板价强控
                else:
                    estimated_remaining_eps += (last_year_eps / 4.0)

            final_eps = reported_eps + estimated_remaining_eps
            if category == "A" and len(missing_quarters) > 0:
                final_eps -= 0.05  # A类留余量

            return round(final_eps, 2)
        except Exception:
            return 1.5
