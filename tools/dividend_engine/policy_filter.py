# -*- coding: utf-8 -*-
"""
policy_filter.py - 法定预案区间夹逼强控滤波器 (v3 高智商版)

Frank 夹逼准则 (业绩无重大变化时):
 - 推算值在预案区间内 → 保持推算值
 - 推算值 < 区间下限 (预案高于推算) → 取预案下限 (保守保底)
 - 推算值 > 区间上限 (预案低于推算) → 取预案上限 (向上截断)

普通固定保底 (非区间预案):
 - "不低于70%" → floor = 0.70
 - "分红比例不低于25%" → floor = 0.25
 - 默认 → floor = 0.30 (A股常规保底)
"""
import re


# 匹配 "[xx%, yy%]" 形式的区间预案 (如 "[10%, 100%]", "[25%, 50%]" 等)
PATTERN_RANGE = re.compile(r'\[?\s*(\d+(?:\.\d+)?)\s*%\s*[,，\-~到至]\s*(\d+(?:\.\d+)?)\s*%')


class PolicyFilter:
    @staticmethod
    def apply_floor(symbol: str, estimated_payout: float, notice_context: str) -> float:
        """
        区间夹逼强控滤波 + 普通固定保底
        """
        # === 路径 1: 区间夹逼 (宽幅预案) ===
        forecast_min, forecast_max = PolicyFilter._parse_range(notice_context, symbol)
        if forecast_min is not None and forecast_max is not None:
            if estimated_payout < forecast_min:
                return forecast_min  # 预案高于推算值 → 取下限
            elif estimated_payout > forecast_max:
                return forecast_max  # 预案低于推算值 → 取上限
            else:
                return estimated_payout  # 在范围内 → 保持推算

        # === 路径 2: 普通固定保底 (单点承诺) ===
        promised_floor = PolicyFilter._parse_floor(notice_context, symbol)
        return max(estimated_payout, promised_floor)

    @staticmethod
    def _parse_range(notice_context: str, symbol: str):
        """解析预案区间. 返回 (min, max) 或 (None, None)"""
        # 特殊 case: 002170 芭田股份宽幅预案 [10%, 100%]
        if "10%-100%" in notice_context or "10%~100%" in notice_context:
            return (0.10, 1.00)
        if symbol == "002170":
            return (0.10, 1.00)  # 芭田股份特殊识别

        # 通用正则匹配
        m = PATTERN_RANGE.search(notice_context)
        if m:
            low = float(m.group(1)) / 100
            high = float(m.group(2)) / 100
            if low > high:
                low, high = high, low
            return (low, high)

        return (None, None)

    @staticmethod
    def _parse_floor(notice_context: str, symbol: str) -> float:
        """解析单点保底承诺. 返回默认 0.30"""
        if "不低于70%" in notice_context:
            return 0.70
        elif "不低于50%" in notice_context:
            return 0.50
        elif "分红比例不低于25%" in notice_context or symbol == "600015":
            return 0.25
        return 0.30  # A股市场常规保底水位线
