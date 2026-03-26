import type { APIRoute } from 'astro';

const TENCENT_API = "https://qt.gtimg.cn/q={}";
const YAHOO_API = "https://query1.finance.yahoo.com/v8/finance/chart/{}";

interface IndexData {
  name: string;
  code: string;
  price: number;
  change: number;
  change_pct: number;
  high?: number;
  low?: number;
  volume?: number;
  turnover?: number;
}

async function getTencentQuote(codes: string[]): Promise<IndexData[]> {
  if (!codes.length) return [];
  
  const query = codes.join(",");
  const url = TENCENT_API.format(query);
  
  try {
    const res = await fetch(url, {
      headers: {
        "Referer": "https://finance.qq.com",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
      }
    });
    
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    
    const text = await res.text();
    const results: IndexData[] = [];
    
    for (const line of text.trim().split('\n')) {
      const trimmed = line.trim();
      if (!trimmed.includes('~')) continue;
      
      try {
        const parts = trimmed.split('"')[1].split('~');
        if (parts.length < 50) continue;
        
        const code = parts[2];
        const prev = parseFloat(parts[4]) || 0;
        const curr = parseFloat(parts[3]) || 0;
        const chg = curr - prev;
        const pct = prev !== 0 ? (chg / prev * 100) : 0;
        
        results.push({
          name: parts[1],
          code: code,
          price: Math.round(curr * 100) / 100,
          change: Math.round(chg * 100) / 100,
          change_pct: Math.round(pct * 100) / 100,
          high: parseFloat(parts[33]) || 0,
          low: parseFloat(parts[34]) || 0,
          volume: parseInt(parts[6]) || 0,
          turnover: parseFloat(parts[38]) || 0,
        });
      } catch (e) {
        continue;
      }
    }
    
    return results;
  } catch (e) {
    console.error('Tencent API error:', e);
    return [];
  }
}

async function getUsIndex(symbol: string, name: string, code: string): Promise<IndexData> {
  const url = YAHOO_API.format(symbol);
  
  try {
    const res = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
      }
    });
    
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    
    const data = await res.json();
    const result = data?.chart?.result?.[0];
    
    if (!result) return { name, code, price: 0, change: 0, change_pct: 0 };
    
    const meta = result.meta;
    const price = meta.regularMarketPrice || 0;
    const prevClose = meta.previousClose || price;
    const chg = price - prevClose;
    const pct = prevClose !== 0 ? (chg / prevClose * 100) : 0;
    
    return {
      name,
      code,
      price: Math.round(price * 100) / 100,
      change: Math.round(chg * 100) / 100,
      change_pct: Math.round(pct * 100) / 100,
    };
  } catch (e) {
    console.error(`Yahoo API error for ${symbol}:`, e);
    return { name, code, price: 0, change: 0, change_pct: 0 };
  }
}

export const GET: APIRoute = async () => {
  try {
    const now = new Date();
    const updateTime = now.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    }).replace(/\//g, '-');
    
    // Fetch A-share indices
    const indices = await getTencentQuote([
      'sh000001',  // 上证指数
      'sz399001',  // 深证成指
      'sz399006',  // 创业板指
      'sh000688',  // 科创50
    ]);
    
    // Fetch US and global indices
    const usIndices = await Promise.all([
      getUsIndex('^IXIC', '纳斯达克', 'IXIC'),
      getUsIndex('^DJI', '道琼斯', 'DJI'),
      getUsIndex('^GSPC', '标普500', 'SPX'),
      getUsIndex('^N225', '日经225', 'N225'),
      getUsIndex('^HSI', '恒生指数', 'HSI'),
      getUsIndex('^KS11', '韩国综合', 'KS11'),
      getUsIndex('^KQ11', '韩国科斯达克', 'KQ11'),
      getUsIndex('^GDAXI', '德国DAX', 'GDAXI'),
      getUsIndex('^FTSE', '英国富时', 'FTSE'),
      getUsIndex('^FCHI', '法国CAC40', 'FCHI'),
    ]);
    
    // Fetch futures
    const futures = await Promise.all([
      getUsIndex('XIN9.L', '富时A50', 'XIN9'),
      getUsIndex('NQ=F', '纳指期指', 'NQ'),
      getUsIndex('ES=F', '标普期指', 'ES'),
      getUsIndex('YM=F', '道指期指', 'YM'),
      getUsIndex('BZ=F', '布伦特原油', 'BZ'),
      getUsIndex('GC=F', '纽约黄金', 'GC'),
    ]);
    
    // Fetch stocks
    const stocks = await getTencentQuote([
      'sh600519',  // 贵州茅台
      'sz000001',  // 平安银行
      'sh600036',  // 招商银行
      'sh601318',  // 中国平安
      'sz000858',  // 五粮液
    ]);
    
    const response = {
      success: true,
      update_time: updateTime,
      indices,
      us_indices: usIndices,
      futures,
      stocks,
      summary: {
        limit_up_count: 0,
        limit_down_count: 0,
      },
    };
    
    return new Response(JSON.stringify(response), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
      },
    });
  } catch (e) {
    console.error('Update error:', e);
    return new Response(JSON.stringify({ success: false, error: '更新失败' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
