# -*- coding: utf-8 -*-
"""
policy_filter.py - 法定股东回报规划红线过滤器 (Step 5)
"""
class PolicyFilter:
    @staticmethod
    def apply_floor(symbol: str, final_payout: float, notice_context: str) -> float:
        """白纸黑字《股东回报规划》强控滤波，低于底线强制拉高对齐"""
        promised_floor = 0.30
        if "不低于70%" in notice_context:
            promised_floor = 0.70
        elif "不低于50%" in notice_context:
            promised_floor = 0.50
        elif "分红比例不低于25%" in notice_context or symbol == "600015":
            promised_floor = 0.25

        return max(final_payout, promised_floor)
