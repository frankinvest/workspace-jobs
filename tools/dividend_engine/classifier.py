# -*- coding: utf-8 -*-
"""
classifier.py - 申万穿透 + 巨潮官方行业兜底的企业 A/B/C 分类器 (v3 高智商版)

设计哲学:
 - 主路径: 巨潮 stock_profile_cninfo 拿"所属行业"字符串 → 关键词匹配
 - 备路径: 申万 stock_industry_clf_hist_sw (旧 6 位代码) → 用前 2 位判断
 - 末路径: 名字硬编码兜底 (芭田→B, 海控→B, 银行→A)
"""
import pandas as pd
import akshare as ak


# 申万旧版 6 位代码 前 2 位 → 一级行业 (用于 stock_industry_clf_hist_sw 返回的旧代码)
SW_OLD_CODE_PREFIX = {
    "22": "基础化工",  # 220301, 220310, 220805 等
    "24": "钢铁",
    "28": "有色金属",
    "61": "农林牧渔",
    "42": "交通运输",  # 航运/海运
    "43": "建筑材料",
    "41": "汽车",
    "62": "食品饮料",
    "63": "家用电器",
    "64": "纺织服饰",
    "48": "银行",
    "45": "公用事业",
    "21": "煤炭",
    "44": "石油石化",
}


# 一级行业 → 类别 决策表
LEVEL1_TO_CATEGORY = {
    "银行": "A",
    "公用事业": "A",  # 电力/水务/燃气
    "食品饮料": "A",  # 白酒
    "家用电器": "A",
    "交通运输": "B",  # 航运/海运
    "基础化工": "B",  # 化肥/农药/纯碱
    "钢铁": "B",
    "有色金属": "B",
    "煤炭": "B",
    "石油石化": "B",
    "农林牧渔": "B",  # 农产品
    "建筑材料": "C",
    "建筑装饰": "C",
    "汽车": "C",  # 资本开支大
    "电力设备": "C",
    "机械设备": "C",
    "国防军工": "C",
    "计算机": "C",
    "传媒": "C",
    "通信": "C",
    "环保": "C",
    "美容护理": "C",
    "医药生物": "C",
    "房地产": "C",  # 资本开支大
    "电子": "C",
    "商贸零售": "C",
    "社会服务": "C",
    "综合": "C",
    "纺织服饰": "C",
    "轻工制造": "C",
    "非银金融": "C",
}


# 巨潮"所属行业"字符串 → 分类 关键词
INDUSTRY_B_KEYWORDS = [
    "化工", "化肥", "复合肥", "磷肥", "钾肥", "纯碱", "农药", "氯碱",
    "钢铁", "有色金属", "铜冶炼", "铝", "锌", "镍", "黄金", "白银",
    "航运", "海运", "船舶", "港口", "远洋", "水上运输",
    "煤炭", "焦煤", "焦炭", "石油", "石化", "天然气", "油气",
    "农产品", "畜牧", "饲料", "种植", "林业", "渔业",
]

INDUSTRY_A_KEYWORDS = [
    "银行", "货币金融",
    "电力", "热力", "发电", "电网", "供电",
    "水务", "供水", "自来水",
    "燃气", "管道燃气",
    "白酒", "酿酒", "乳品", "烟草",
]


# 名字兜底 (巨潮接口失败 + 申万接口失败 时的终极兜底)
NAME_FALLBACK = {
    "A": ["银行", "电力", "公用", "水务", "燃气", "白酒", "公用事业"],
    "B": ["航运", "海控", "海运", "煤炭", "有色", "化工", "化肥", "钢铁", "磷肥", "钾肥", "复合肥", "纯碱", "芭田"],
    "C": [],
}


class StockClassifier:
    @staticmethod
    def classify(hub, symbol: str, name: str) -> str:
        """
        申万+巨潮行业穿透 → A/B/C 分类

        优先级:
         1. 巨潮 stock_profile_cninfo 拿"所属行业"字符串 → 关键词匹配
         2. 申万 stock_industry_clf_hist_sw 拿当前 6 位代码 → 前 2 位映射一级
         3. 名字硬编码兜底
        """
        # 路径 1: 巨潮所属行业字符串 (最权威)
        try:
            df = ak.stock_profile_cninfo(symbol=symbol)
            if not df.empty and '所属行业' in df.columns:
                industry_str = str(df['所属行业'].iloc[0])
                if industry_str and industry_str != 'nan':
                    return StockClassifier._classify_by_industry_str(industry_str, name)
        except Exception:
            pass

        # 路径 2: 申万旧代码前 2 位
        try:
            df_sw = ak.stock_industry_clf_hist_sw()
            clean = "".join(filter(str.isdigit, symbol))
            sub = df_sw[df_sw['symbol'] == clean]
            if not sub.empty:
                latest = sub.sort_values('start_date', ascending=False).iloc[0]
                code6 = str(latest['industry_code'])
                if len(code6) == 6:
                    level1 = SW_OLD_CODE_PREFIX.get(code6[:2])
                    if level1 and level1 in LEVEL1_TO_CATEGORY:
                        return LEVEL1_TO_CATEGORY[level1]
        except Exception:
            pass

        # 路径 3: 名字兜底
        return StockClassifier._classify_by_name_fallback(name)

    @staticmethod
    def _classify_by_industry_str(industry_str: str, name: str) -> str:
        """巨潮"所属行业"字符串 → 分类
        优先级: A (稳定) 先判 > B (周期) 后判 > 名字兑底
        """
        # A 先判 (稳定公用事业/银行, 关键词更明确)
        if any(k in industry_str for k in INDUSTRY_A_KEYWORDS):
            return "A"
        # B 后判 (强周期, 排除已匹配 A 的)
        if any(k in industry_str for k in INDUSTRY_B_KEYWORDS):
            return "B"
        return StockClassifier._classify_by_name_fallback(name)

    @staticmethod
    def _classify_by_name_fallback(name: str) -> str:
        """终极名字兜底"""
        for k in NAME_FALLBACK["A"]:
            if k in name:
                return "A"
        for k in NAME_FALLBACK["B"]:
            if k in name:
                return "B"
        return "C"
