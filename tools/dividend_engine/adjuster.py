# -*- coding: utf-8 -*-
"""
adjuster.py - 行业与大股东定性纠偏器 (Step 3 + Step 4 合并)
"""
class QualitativeAdjuster:
    @staticmethod
    def adjust_by_industry(category: str, base_payout: float, llm_context: str) -> float:
        """行业基准纠正：针对周期位置和大额资本开支微调派息率"""
        corrected_payout = base_payout
        if category == "B":
            if "周期顶部" in llm_context or "大周期暴利" in llm_context:
                corrected_payout -= 0.05  # 周期顶部倾向于屯现金防御
            elif "周期谷底" in llm_context:
                corrected_payout += 0.05  # 周期底部释放红利平滑波动
        elif category == "C":
            if any(k in llm_context for k in ["巨额资本开支", "大额收购", "新建产能"]):
                corrected_payout -= 0.10  # 有大额开支下调派息
            elif any(k in llm_context for k in ["出售资产", "处理股票", "出让股权"]):
                corrected_payout += 0.10  # 天降横财上调派息
        return max(0.0, min(1.0, corrected_payout))

    @staticmethod
    def adjust_by_shareholder(current_payout: float, pledge_context: str) -> float:
        """大股东诉求纠正：若大股东急需资金且未减持，大概率通过提高分红抽血自救"""
        if any(k in pledge_context for k in ["急需资金", "高比例股权质押", "财务投资者约定"]):
            return current_payout + 0.08  # 大股东诉求重要性更高，强行调高
        return current_payout
