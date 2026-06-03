# -*- coding: utf-8 -*-
"""
classifier.py - 企业属性 A/B/C 分类器
"""
class StockClassifier:
    @staticmethod
    def classify(symbol: str, name: str) -> str:
        """根据行业归属与历史稳定性硬核判定 A/B/C 三大类"""
        a_keywords = ['银行', '电力', '电信', '铁路', '水务', '燃气']  # A类代表
        b_keywords = ['航运', '海控', '煤炭', '有色', '化工', '钢铁']  # B类代表

        if any(k in name for k in a_keywords) or symbol in ['600519', '600036', '600015']:
            return "A"  # 业绩稳定 + 派息稳定
        elif any(k in name for k in b_keywords) or symbol in ['601919']:
            return "B"  # 业绩不稳定（周期强） + 派息稳定
        else:
            return "C"  # 业绩稳定 + 派息不稳定（资本开支大）
