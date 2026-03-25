#!/usr/bin/env python3
"""
A 股数据获取 - 腾讯行情 API（绕过 eastmoney VPN 拦截）
"""
import requests
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

TENCENT_API = "https://qt.gtimg.cn/q={}"

def get_quote(codes: list) -> pd.DataFrame:
    """
    获取股票实时行情（腾讯行情API）
    codes: 股票代码列表，支持 sh600000、sz000001 格式
    """
    if not codes:
        return pd.DataFrame()
    
    query = ",".join(codes)
    url = TENCENT_API.format(query)
    
    headers = {
        "Referer": "https://finance.qq.com",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    r = requests.get(url, headers=headers, timeout=10)
    r.encoding = 'gbk'
    
    rows = []
    for line in r.text.strip().split('\n'):
        line = line.strip()
        if '~' not in line:
            continue
        # v_sh600000="1~浦发银行~600000~10.10~10.04~10.06~456784~
        try:
            parts = line.split('"')[1].split('~')
            if len(parts) < 10:
                continue
            rows.append({
                '股票名称': parts[1],
                '股票代码': parts[2],
                '当前价': parts[3],
                '昨收': parts[4],
                '今开': parts[5],
                '成交量(手)': parts[6],
                '外盘': parts[7],
                '内盘': parts[8],
                '买一': parts[9],
                '卖一': parts[19] if len(parts) > 19 else '',
            })
        except Exception:
            continue
    
    return pd.DataFrame(rows)

def get_index() -> dict:
    """获取主要指数（上证、深证、创业板、科创50）"""
    codes = ['sh000001', 'sz399001', 'sz399006', 'sh000688']
    names = {'sh000001': '上证指数', 'sz399001': '深证成指', 'sz399006': '创业板指', 'sh000688': '科创50'}
    
    df = get_quote(codes)
    result = {}
    for _, row in df.iterrows():
        code = row['股票代码']
        prefix = 'sh' if code.startswith('6') else 'sz'
        key = f"{prefix}{code}"
        name = names.get(key, row['股票名称'])
        prev = float(row['昨收'])
        curr = float(row['当前价'])
        chg = curr - prev
        pct = chg / prev * 100
        result[name] = {'当前价': f"{curr:.2f}", '涨跌': f"{chg:+.2f}", '涨跌幅': f"{pct:+.2f}%"}
    
    return result

if __name__ == "__main__":
    print("=== 腾讯A股行情测试 ===")
    df = get_quote(['sh600000', 'sz000001', 'sz000002', 'sh601318'])
    print(df)
    print("\n=== 主要指数 ===")
    idx = get_index()
    for name, data in idx.items():
        print(f"{name}: {data['当前价']} {data['涨跌']} ({data['涨跌幅']})")
