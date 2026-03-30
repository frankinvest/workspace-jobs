import type { APIRoute } from 'astro';

interface MarketData {
  indices: { name: string; code: string; price: number; change: number; change_pct: number }[];
  usIndices: { name: string; code: string; price: number; change: number; change_pct: number }[];
  futures: { name: string; code: string; price: number; change: number; change_pct: number }[];
  stocks: { name: string; code: string; price: number; change: number; change_pct: number }[];
  updateTime: string;
  dataSource: string;
}

// 内存缓存
const dataCache: Map<string, { data: MarketData; timestamp: number }> = new Map();
const CACHE_DURATION = 5 * 60 * 1000; // 5 分钟缓存

// 从本地 JSON 文件加载数据
async function loadMarketDataFromJSON(): Promise<MarketData> {
  const dataPath = new URL('../../public/data/market_data.json', import.meta.url);
  
  try {
    const response = await fetch(dataPath);
    if (!response.ok) throw new Error('文件加载失败');
    
    const data = await response.json();
    
    return {
      indices: data.indices || [],
      usIndices: data.usIndices || [],
      futures: data.futures || [],
      stocks: data.stocks || [],
      dataSource: 'Wind 金融数据 (本地)',
      updateTime: data.updateTime || new Date().toLocaleString('zh-CN', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false
      }).replace(/\//g, '-')
    };
  } catch (error) {
    console.warn('本地数据文件加载失败，使用默认数据:', error);
    return getFallbackData();
  }
}

// 获取回退数据
function getFallbackData(): MarketData {
  const now = new Date();
  return {
    indices: [
      { name: '上证指数', code: 'SH000001', price: 3088.23, change: 7.45, change_pct: 0.24 },
      { name: '深证成指', code: 'SZ399001', price: 9727.03, change: -25.32, change_pct: -0.26 },
      { name: '创业板指', code: 'SZ399006', price: 1935.76, change: 8.92, change_pct: 0.46 },
      { name: '科创 50', code: 'SH000688', price: 768.45, change: 1.85, change_pct: 0.24 },
    ],
    usIndices: [
      { name: '纳斯达克', code: 'IXIC', price: 20928.97, change: -18.97, change_pct: -0.09 },
      { name: '道琼斯', code: 'DJI', price: 45452.58, change: 283.80, change_pct: 0.63 },
      { name: '标普 500', code: 'SPX', price: 5892.44, change: 15.22, change_pct: 0.26 },
      { name: '日经 225', code: 'N225', price: 38915.87, change: 120.50, change_pct: 0.31 },
      { name: '恒生指数', code: 'HSI', price: 24951.88, change: -325.60, change_pct: -1.29 },
    ],
    futures: [
      { name: '富时 A50', code: 'XIN9', price: 12845.50, change: 85.20, change_pct: 0.67 },
      { name: '纳指期指', code: 'NQ', price: 22485.75, change: 95.25, change_pct: 0.43 },
      { name: '标普期指', code: 'ES', price: 5905.25, change: 18.75, change_pct: 0.32 },
      { name: '布伦特原油', code: 'BZ', price: 107.16, change: 2.45, change_pct: 2.34 },
      { name: '纽约黄金', code: 'GC', price: 2895.40, change: -12.60, change_pct: -0.43 },
    ],
    stocks: [
      { name: '贵州茅台', code: 'SH600519', price: 1385.50, change: 8.50, change_pct: 0.62 },
      { name: '平安银行', code: 'SZ000001', price: 11.02, change: 0.05, change_pct: 0.46 },
      { name: '招商银行', code: 'SH600036', price: 33.85, change: -0.25, change_pct: -0.73 },
      { name: '中国平安', code: 'SH601318', price: 46.78, change: 0.68, change_pct: 1.48 },
      { name: '五粮液', code: 'SZ000858', price: 138.25, change: -1.45, change_pct: -1.04 },
    ],
    dataSource: 'Wind 金融数据 (示例)',
    updateTime: now.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false
    }).replace(/\//g, '-')
  };
}

// 获取数据（带缓存）
async function getMarketData(forceRefresh = false): Promise<MarketData> {
  const cacheKey = 'market_data';
  const cached = dataCache.get(cacheKey);
  
  // 检查缓存是否有效
  if (cached && !forceRefresh) {
    const age = Date.now() - cached.timestamp;
    if (age < CACHE_DURATION) {
      return cached.data;
    }
  }
  
  // 加载新数据
  const data = await loadMarketDataFromJSON();
  
  // 更新缓存
  dataCache.set(cacheKey, {
    data,
    timestamp: Date.now()
  });
  
  return data;
}

export const GET: APIRoute = async (context) => {
  try {
    // 检查是否需要强制刷新
    const url = new URL(context.url);
    const forceRefresh = url.searchParams.get('refresh') === 'true';
    
    const data = await getMarketData(forceRefresh);
    
    const response = {
      success: true,
      indices: data.indices,
      us_indices: data.usIndices,
      futures: data.futures,
      stocks: data.stocks,
      lme_metals: [],
      shfe_metals: [],
      update_time: data.updateTime,
      dataSource: data.dataSource,
      cached: !forceRefresh && dataCache.has('market_data'),
      cacheDuration: `${CACHE_DURATION / 1000}秒`,
      summary: {
        limit_up_count: [
          ...data.indices,
          ...data.usIndices,
          ...data.futures,
          ...data.stocks
        ].filter(i => i.change_pct > 0).length,
        limit_down_count: [
          ...data.indices,
          ...data.usIndices,
          ...data.futures,
          ...data.stocks
        ].filter(i => i.change_pct < 0).length,
      },
    };
    
    return new Response(JSON.stringify(response), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': forceRefresh 
          ? 'no-cache, no-store, must-revalidate' 
          : `max-age=${CACHE_DURATION / 1000}, stale-while-revalidate=300`,
      },
    });
  } catch (error) {
    console.error('Update error:', error);
    return new Response(JSON.stringify({ 
      success: false, 
      error: '数据获取失败',
      fallback: true
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};

// POST 端点：强制刷新数据
export const POST: APIRoute = async (context) => {
  try {
    console.log('🔄 强制刷新市场数据...');
    
    // 清除缓存
    dataCache.clear();
    
    // 重新加载数据
    const data = await getMarketData(true);
    
    return new Response(JSON.stringify({
      success: true,
      message: '数据已刷新',
      ...data,
      cached: false,
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
      },
    });
  } catch (error) {
    console.error('Refresh error:', error);
    return new Response(JSON.stringify({ 
      success: false, 
      error: '刷新失败'
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};
