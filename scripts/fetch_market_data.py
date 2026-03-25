#!/usr/bin/env python3
"""
财经早餐 - 市场数据获取脚本
使用腾讯行情 API（绕过 eastmoney VPN 拦截）
外盘指数使用 Yahoo Finance API
"""

import json
import os
from datetime import datetime
import requests
import pandas as pd

# 数据输出目录
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'public', 'data')
os.makedirs(OUTPUT_DIR, exist_ok=True)

TENCENT_API = "https://qt.gtimg.cn/q={}"
YAHOO_API = "https://query1.finance.yahoo.com/v8/finance/chart/{}"

def get_tencent_quote(codes: list) -> pd.DataFrame:
    """获取股票实时行情（腾讯行情API）"""
    if not codes:
        return pd.DataFrame()
    
    query = ",".join(codes)
    url = TENCENT_API.format(query)
    
    headers = {
        "Referer": "https://finance.qq.com",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = 'gbk'
    except Exception as e:
        print(f"请求失败: {e}")
        return pd.DataFrame()
    
    rows = []
    for line in r.text.strip().split('\n'):
        line = line.strip()
        if '~' not in line:
            continue
        try:
            parts = line.split('"')[1].split('~')
            if len(parts) < 50:
                continue
            code = parts[2]
            prev = float(parts[4]) if parts[4] else 0
            curr = float(parts[3]) if parts[3] else 0
            chg = curr - prev
            pct = (chg / prev * 100) if prev != 0 else 0
            
            rows.append({
                'code': code,
                'name': parts[1],
                'price': curr,
                'prev_close': prev,
                'open': float(parts[5]) if parts[5] else 0,
                'volume': int(parts[6]) if parts[6] else 0,
                'change': chg,
                'change_pct': pct,
                'high': float(parts[33]) if parts[33] else 0,
                'low': float(parts[34]) if parts[34] else 0,
                'turnover': float(parts[38]) if parts[38] else 0,
                'pe': float(parts[39]) if parts[39] else 0,
                'pb': float(parts[46]) if parts[46] else 0,
            })
        except Exception:
            continue
    
    return pd.DataFrame(rows)

def get_us_index(symbol: str) -> dict:
    """获取外盘指数（通过 Yahoo Finance）"""
    symbol_map = {
        'nasdaq': '^IXIC',
        'dow': '^DJI',
        'sp500': '^GSPC',
        'nikkei': '^N225',
        'hangsheng': '^HSI',
        'ftse': '^FTSE',
        'dax': '^GDAXI',
    }
    
    yahoo_symbol = symbol_map.get(symbol, symbol)
    url = YAHOO_API.format(yahoo_symbol)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        result = data.get('chart', {}).get('result', [])
        if result:
            meta = result[0].get('meta', {})
            price = meta.get('regularMarketPrice', 0)
            prev_close = meta.get('previousClose', price)
            chg = price - prev_close
            pct = (chg / prev_close * 100) if prev_close != 0 else 0
            return {
                'price': round(price, 2),
                'change': round(chg, 2),
                'change_pct': round(pct, 2),
            }
    except Exception as e:
        print(f"获取 {symbol} 失败: {e}")
    
    return {'price': 0, 'change': 0, 'change_pct': 0}

def get_index_data():
    """获取A股指数数据"""
    indices = [
        'sh000001',  # 上证指数
        'sz399001',  # 深证成指
        'sz399006',  # 创业板指
        'sh000688',  # 科创50
    ]
    
    print(f"获取A股指数数据: {indices}")
    df = get_tencent_quote(indices)
    
    result = []
    for _, row in df.iterrows():
        item = {
            "name": row['name'],
            "code": row['code'],
            "price": round(row['price'], 2),
            "change": round(row['change'], 2),
            "change_pct": round(row['change_pct'], 2),
            "high": round(row['high'], 2),
            "low": round(row['low'], 2),
            "volume": row['volume'],
            "turnover": row['turnover'],
        }
        result.append(item)
        print(f"  {item['name']}: {item['price']} ({item['change_pct']:+.2f}%)")
    
    return result

def get_us_indices_data() -> list:
    """获取外盘指数数据"""
    indices = [
        {'symbol': 'nasdaq', 'name': '纳斯达克', 'code': 'IXIC'},
        {'symbol': 'dow', 'name': '道琼斯', 'code': 'DJI'},
        {'symbol': 'sp500', 'name': '标普500', 'code': 'SPX'},
        {'symbol': 'nikkei', 'name': '日经225', 'code': 'N225'},
        {'symbol': 'hangsheng', 'name': '恒生指数', 'code': 'HSI'},
        {'symbol': '^KS11', 'name': '韩国综合', 'code': 'KS11'},
        {'symbol': '^KQ11', 'name': '韩国科斯达克', 'code': 'KQ11'},
        {'symbol': '^GDAXI', 'name': '德国DAX', 'code': 'GDAXI'},
        {'symbol': '^FTSE', 'name': '英国富时', 'code': 'FTSE'},
        {'symbol': '^FCHI', 'name': '法国CAC40', 'code': 'FCHI'},
    ]
    
    result = []
    for idx in indices:
        data = get_us_index(idx['symbol'])
        item = {
            'name': idx['name'],
            'code': idx['code'],
            'price': data['price'],
            'change': data['change'],
            'change_pct': data['change_pct'],
        }
        result.append(item)
        print(f"  {item['name']}: {item['price']} ({item['change_pct']:+.2f}%)")
    
    return result

def get_futures_data() -> list:
    """获取期指数据（A50、纳指期货、标普期指、布伦特原油、黄金等）"""
    futures = [
        {'symbol': 'XIN9.L', 'name': '富时A50', 'code': 'XIN9'},
        {'symbol': 'NQ=F', 'name': '纳指期指', 'code': 'NQ'},
        {'symbol': 'ES=F', 'name': '标普期指', 'code': 'ES'},
        {'symbol': 'YM=F', 'name': '道指期指', 'code': 'YM'},
        {'symbol': 'BZ=F', 'name': '布伦特原油', 'code': 'BZ'},
        {'symbol': 'GC=F', 'name': '黄金期货', 'code': 'GC'},
    ]
    
    result = []
    for ft in futures:
        data = get_us_index(ft['symbol'])
        item = {
            'name': ft['name'],
            'code': ft['code'],
            'price': data['price'],
            'change': data['change'],
            'change_pct': data['change_pct'],
        }
        result.append(item)
        if item['price'] > 0:
            print(f"  {item['name']}: {item['price']} ({item['change_pct']:+.2f}%)")
        else:
            print(f"  {item['name']}: 获取失败")
    
    return result

def get_stock_data():
    """获取个股行情"""
    stocks = [
        'sh600519',  # 贵州茅台
        'sz000001',  # 平安银行
        'sh600036',  # 招商银行
        'sh601318',  # 中国平安
        'sz000858',  # 五粮液
    ]
    
    print(f"获取个股数据: {stocks}")
    df = get_tencent_quote(stocks)
    
    result = []
    for _, row in df.iterrows():
        item = {
            "name": row['name'],
            "code": row['code'],
            "price": round(row['price'], 2),
            "change": round(row['change'], 2),
            "change_pct": round(row['change_pct'], 2),
            "volume": row['volume'],
            "turnover": row['turnover'],
            "pe": row['pe'],
            "pb": row['pb'],
            "high": round(row['high'], 2),
            "low": round(row['low'], 2),
        }
        result.append(item)
        print(f"  {item['name']}: {item['price']} ({item['change_pct']:+.2f}%)")
    
    return result

def get_market_summary():
    """获取市场概况（涨停跌停数量）"""
    try:
        import akshare as ak
        today = datetime.now().strftime("%Y%m%d")
        
        try:
            df_limit_up = ak.stock_zt_pool_em(date=today)
            limit_up_count = len(df_limit_up) if not df_limit_up.empty else 0
        except:
            limit_up_count = 0
        
        try:
            df_limit_down = ak.stock_zt_pool_em(date=today, zt_pool_date="dt")
            limit_down_count = len(df_limit_down) if not df_limit_down.empty else 0
        except:
            limit_down_count = 0
        
        return {
            "limit_up_count": limit_up_count,
            "limit_down_count": limit_down_count,
        }
    except Exception as e:
        print(f"获取市场概况失败: {e}")
        return {
            "limit_up_count": 0,
            "limit_down_count": 0,
        }

def main():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始获取市场数据...")
    
    data = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "indices": [],
        "us_indices": [],
        "futures": [],
        "stocks": [],
        "summary": {},
    }
    
    # 获取 A 股指数数据
    print("\n--- A股指数 ---")
    data["indices"] = get_index_data()
    
    # 获取外盘指数数据
    print("\n--- 外盘指数 ---")
    data["us_indices"] = get_us_indices_data()
    
    # 获取期指数据
    print("\n--- 期指期货 ---")
    data["futures"] = get_futures_data()
    
    # 获取个股数据
    print("\n--- 个股数据 ---")
    data["stocks"] = get_stock_data()
    
    # 获取市场概况
    print("\n--- 市场概况 ---")
    data["summary"] = get_market_summary()
    print(f"  涨停: {data['summary']['limit_up_count']} 只 | 跌停: {data['summary']['limit_down_count']} 只")
    
    # 保存数据
    output_file = os.path.join(OUTPUT_DIR, 'market_data.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 数据已保存到: {output_file}")
    print(f"✅ 更新时间是: {data['update_time']}")

if __name__ == "__main__":
    main()
