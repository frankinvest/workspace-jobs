// Vercel serverless function: 全球大宗期货 + 美股/亚太指数聚合 (ESM).
//
//   GET /api/global-markets
//
// 返回 JSON:
//   {
//     "categories": {
//       "energy":       [ ... ],
//       "precious":     [ ... ],
//       "metals":       [ ... ],
//       "agriculture":  [ ... ],
//       "us_index":     [ ... ],
//       "asia_index":   [ ... ]
//     },
//     "asOf": 1756420800000,
//     "source": "tencent|sina|yahoo|mixed|none",
//     "errors": [ ... ]
//   }
//
// 数据源策略（多源 race，Promise.race 取最快成功）：
//   - 国内大宗期货 → 新浪 hq.sinajs.cn (nf_* 格式，GBK 解码)  [Codex 18:00 反馈：腾讯 nf 前缀在 qt.gtimg.cn 不存在]
//   - 港股指数 → 腾讯 qt.gtimg.cn (hkHSI)
//   - 美股指数 → 腾讯 qt.gtimg.cn (usINX/usIXIC/usDJI)  [parts[3]=价格, parts[34]=涨跌幅 — 我之前猜错]
//   - 国际期货（COMEX/NYMEX/CBOT/LME）+ 日韩台 → Yahoo Finance v8
//
// 缓存：5 分钟内存缓存

import https from 'node:https';

const TIMEOUT_MS = 8000;
const USER_AGENT = 'Mozilla/5.0 (Jobs-GlobalMarkets)';
const CACHE_TTL_MS = 5 * 60 * 1000;

let cache = { data: null, expiresAt: 0 };

// ── 网络工具 ──────────────────────────────────────────────
function fetchUrl(rawUrl, headers = {}, encoding = 'utf-8') {
  return new Promise((resolve, reject) => {
    let u;
    try { u = new URL(rawUrl); }
    catch (err) { reject(new Error('invalid url')); return; }
    const req = https.get(
      {
        hostname: u.hostname,
        path: u.pathname + u.search,
        headers: { 'User-Agent': USER_AGENT, ...headers },
        timeout: TIMEOUT_MS,
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error('http ' + res.statusCode));
            return;
          }
          const buf = Buffer.concat(chunks);
          const text = encoding === 'gbk' ? buf.toString('latin1') : buf.toString('utf-8');
          resolve(text);
        });
        res.on('error', reject);
      },
    );
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

// ── 期货 / 指数代码定义（Frank 2026-09-07 17:57【纵横东西】模块）──
const CATEGORIES = {
  energy: {
    label: '能源',
    items: [
      { code: 'CL=F',  nameZh: 'WTI 原油',   unit: 'USD/桶', src: 'yahoo' },
      { code: 'BZ=F',  nameZh: '布伦特原油', unit: 'USD/桶', src: 'yahoo' },
      { code: 'NG=F',  nameZh: '天然气',     unit: 'USD/MMBtu', src: 'yahoo' },
      { code: 'HO=F',  nameZh: '取暖油',     unit: 'USD/加仑', src: 'yahoo' },
      { code: 'RB=F',  nameZh: 'RBOB 汽油',  unit: 'USD/加仑', src: 'yahoo' },
    ],
  },
  precious: {
    label: '贵金属',
    items: [
      { code: 'GC=F',  nameZh: 'COMEX 黄金',     unit: 'USD/盎司', src: 'yahoo' },
      { code: 'SI=F',  nameZh: 'COMEX 白银',     unit: 'USD/盎司', src: 'yahoo' },
      { code: 'HG=F',  nameZh: 'COMEX 铜',       unit: 'USD/磅', src: 'yahoo' },
      { code: 'PL=F',  nameZh: 'NYMEX 铂金',     unit: 'USD/盎司', src: 'yahoo' },
      { code: 'PA=F',  nameZh: 'NYMEX 钯金',     unit: 'USD/盎司', src: 'yahoo' },
    ],
  },
  metals: {
    label: '有色金属',
    items: [
      // 新浪 hq.sinajs.cn nf_* 格式（curl 18:20 验证 nf_CU0 有数据）
      { code: 'nf_CU0', nameZh: '沪铜主力',   unit: '元/吨', src: 'sina' },
      { code: 'nf_AL0', nameZh: '沪铝主力',   unit: '元/吨', src: 'sina' },
      { code: 'nf_ZN0', nameZh: '沪锌主力',   unit: '元/吨', src: 'sina' },
      { code: 'nf_NI0', nameZh: '沪镍主力',   unit: '元/吨', src: 'sina' },
      { code: 'nf_SN0', nameZh: '沪锡主力',   unit: '元/吨', src: 'sina' },
      { code: 'nf_PB0', nameZh: '沪铅主力',   unit: '元/吨', src: 'sina' },
    ],
  },
  agriculture: {
    label: '农产品',
    items: [
      // 国内 — 新浪 nf_* 格式
      { code: 'nf_SR0', nameZh: '郑商所白糖',  unit: '元/吨', src: 'sina' },
      { code: 'nf_CF0', nameZh: '郑商所棉花',  unit: '元/吨', src: 'sina' },
      { code: 'nf_M0',  nameZh: '大商所豆粕',  unit: '元/吨', src: 'sina' },
      { code: 'nf_Y0',  nameZh: '大商所豆油',  unit: '元/吨', src: 'sina' },
      { code: 'nf_P0',  nameZh: '大商所棕榈',  unit: '元/吨', src: 'sina' },
      { code: 'nf_C0',  nameZh: '大商所玉米',  unit: '元/吨', src: 'sina' },
      { code: 'nf_I0',  nameZh: '大商所铁矿',  unit: '元/吨', src: 'sina' },
      // 国际 — Yahoo Finance v8
      { code: 'ZC=F',  nameZh: 'CBOT 玉米',    unit: '¢/蒲式耳', src: 'yahoo' },
      { code: 'ZW=F',  nameZh: 'CBOT 小麦',    unit: '¢/蒲式耳', src: 'yahoo' },
      { code: 'ZS=F',  nameZh: 'CBOT 大豆',    unit: '¢/蒲式耳', src: 'yahoo' },
      { code: 'SB=F',  nameZh: 'ICE 11 号糖', unit: '¢/磅',    src: 'yahoo' },
      { code: 'KC=F',  nameZh: 'ICE 阿拉比卡咖啡', unit: '¢/磅', src: 'yahoo' },
      { code: 'CT=F',  nameZh: 'ICE 棉花',     unit: '¢/磅',    src: 'yahoo' },
    ],
  },
  us_index: {
    label: '美股指数',
    items: [
      // 腾讯 qt.gtimg.cn (parts 索引修好后 work — parts[3]=价格, parts[34]=涨跌幅)
      { code: 'usINX', nameZh: '标普 500',     unit: '点', src: 'tencent' },
      { code: 'usIXIC',nameZh: '纳斯达克综合', unit: '点', src: 'tencent' },
      { code: 'usDJI', nameZh: '道琼斯工业',   unit: '点', src: 'tencent' },
    ],
  },
  asia_index: {
    label: '亚太指数',
    items: [
      // 港股 — 腾讯 hkHSI（验证 work）
      { code: 'hkHSI', nameZh: '恒生指数',  unit: '点', src: 'tencent' },
      // 日韩台 — 腾讯/新浪都无数据，尝试 Yahoo (Codex 说有 anti-bot 但还有概率通)
      { code: '^N225', nameZh: '日经 225',  unit: '点', src: 'yahoo' },
      { code: '^KS11', nameZh: '韩国 KOSPI',unit: '点', src: 'yahoo' },
      { code: '^TWII', nameZh: '台湾加权',  unit: '点', src: 'yahoo' },
    ],
  },
};

// ── 腾讯 qt.gtimg.cn 指数解析 ──
// 真实返回结构（curl 18:21 验证 v_usINX）：
//   parts[0]  = 200 (类型代码) 或 100 (港股)
//   parts[1]  = 中文名（GBK latin1 解码后会 mojibake，但字段位置固定）
//   parts[2]  = 英文代码（".INX", "HSI" 等）
//   parts[3]  = 当前价 ⭐
//   parts[4]  = 昨收 ⭐
//   parts[5]  = 今开
//   parts[33] = 涨跌额
//   parts[34] = 涨跌幅（%） ⭐
async function fetchTencentIndex(code) {
  const url = 'https://qt.gtimg.cn/q=' + code;
  try {
    const text = await fetchUrl(url, {}, 'gbk');
    if (!text || text.includes('pv_none_match')) return null;
    const match = text.match(/="([^"]+)"/);
    if (!match) return null;
    const parts = match[1].split('~');
    const price = parseFloat(parts[3]);
    const prevClose = parseFloat(parts[4]);
    const changePct = parseFloat(parts[34]);
    if (isNaN(price) || price <= 0) return null;
    return {
      price,
      prevClose: isNaN(prevClose) ? null : prevClose,
      changePct: isNaN(changePct) ? null : changePct,
      source: 'tencent',
      asOf: Date.now(),
    };
  } catch (err) {
    return null;
  }
}

// ── 新浪 hq.sinajs.cn 期货解析 ──
// 真实返回（curl 18:21 验证 nf_CU0）：
//   var hq_str_nf_CU0="ͭ����,150000,108760.000,109580.000,108700.000,109410.000,109410.000,109420.000,109410.000,109210.000,109110.000,59,4,214449.000,70006,��,ͭ,2026-09-07,1,,,,,,,,,109213.621,0.000,0,"
//   parts[0]  = 中文名
//   parts[1]  = 合约乘数 / 交易单位
//   parts[2]  = 今开
//   parts[3]  = 最高
//   parts[4]  = 最低
//   parts[5]  = 当前价 ⭐
//   ...
//   parts[29] = 昨结（settlement price，前收盘）⭐
//   parts[30] = 涨跌额
//   parts[31] = 涨跌幅（%） ⭐
async function fetchSinaFutures(code) {
  const url = 'https://hq.sinajs.cn/list=' + code;
  try {
    const text = await fetchUrl(url, { Referer: 'https://finance.sina.com.cn/' }, 'gbk');
    if (!text) return null;
    const match = text.match(/"([^"]+)"/);
    if (!match) return null;
    const parts = match[1].split(',');
    if (parts.length < 6) return null;
    const price = parseFloat(parts[5]);
    const prevClose = parts.length > 29 ? parseFloat(parts[29]) : NaN;
    const changePct = parts.length > 31 ? parseFloat(parts[31]) : NaN;
    if (isNaN(price) || price <= 0) return null;
    // 兜底：如果新浪没给昨结，用 (price - 涨跌额) 推
    const prevCloseFallback = (isNaN(prevClose) && parts.length > 30)
      ? price - parseFloat(parts[30])
      : prevClose;
    return {
      price,
      prevClose: isNaN(prevCloseFallback) ? null : prevCloseFallback,
      changePct: isNaN(changePct) ? null : changePct,
      source: 'sina',
      asOf: Date.now(),
    };
  } catch (err) {
    return null;
  }
}

// ── 新浪 hq.sinajs.cn 指数解析（gb_*/int_*）──
// 真实返回（curl 18:21 验证 gb_ixic）：
//   var hq_str_gb_ixic="纳斯达克,26506.9901,-0.29,2026-09-05 05:30:00,-77.0699,26587.8961,26628.5841,26444.8426,..."
//   parts[0] = 中文名
//   parts[1] = 当前价 ⭐
//   parts[2] = 涨跌幅（%） ⭐
//   parts[3] = 时间
//   parts[4] = 涨跌额
//   parts[5] = 最高
//   parts[6] = 今开
//   parts[7] = 最低
async function fetchSinaIndex(code) {
  const url = 'https://hq.sinajs.cn/list=' + code;
  try {
    const text = await fetchUrl(url, { Referer: 'https://finance.sina.com.cn/' }, 'gbk');
    if (!text) return null;
    const match = text.match(/"([^"]+)"/);
    if (!match) return null;
    const parts = match[1].split(',');
    if (parts.length < 3) return null;
    const price = parseFloat(parts[1]);
    const changePct = parseFloat(parts[2]);
    if (isNaN(price) || price <= 0) return null;
    return {
      price,
      prevClose: null,
      changePct: isNaN(changePct) ? null : changePct,
      source: 'sina',
      asOf: Date.now(),
    };
  } catch (err) {
    return null;
  }
}

// ── Yahoo Finance v8 chart API ──
async function fetchYahooQuote(code) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(code)}?interval=1d&range=2d`;
  try {
    const text = await fetchUrl(url, { 'Accept': 'application/json' });
    if (!text) return null;
    const json = JSON.parse(text);
    const result = json?.chart?.result?.[0];
    if (!result) return null;
    const meta = result.meta || {};
    const price = meta.regularMarketPrice;
    const prevClose = meta.chartPreviousClose || meta.previousClose;
    const changePct = meta.regularMarketChangePercent;
    if (typeof price !== 'number' || price <= 0) return null;
    return {
      price,
      prevClose: typeof prevClose === 'number' ? prevClose : null,
      changePct: typeof changePct === 'number' ? changePct : null,
      source: 'yahoo',
      asOf: (meta.regularMarketTime ? meta.regularMarketTime * 1000 : Date.now()),
    };
  } catch (err) {
    return null;
  }
}

// ── 调度 ──
async function fetchOne(item) {
  switch (item.src) {
    case 'tencent':
      return fetchTencentIndex(item.code);
    case 'sina':
      // 用 code 前缀区分期货/指数
      if (item.code.startsWith('nf_') || item.code.startsWith('NF_')) {
        return fetchSinaFutures(item.code);
      }
      return fetchSinaIndex(item.code);
    case 'yahoo':
      return fetchYahooQuote(item.code);
    default:
      return null;
  }
}

// ── 主 handler ──
export default async function handler(req, res) {
  try {
    res.setHeader('Cache-Control', 'no-store, max-age=0');
    res.setHeader('Content-Type', 'application/json; charset=utf-8');

    if (req.method !== 'GET') {
      res.status(405).json({ error: 'Method not allowed' });
      return;
    }

    const now = Date.now();
    if (cache.data && cache.expiresAt > now) {
      res.status(200).json({ ...cache.data, cached: true });
      return;
    }

    const tasks = [];
    for (const [catKey, cat] of Object.entries(CATEGORIES)) {
      for (const item of cat.items) {
        tasks.push({ catKey, item, p: fetchOne(item) });
      }
    }

    const results = await Promise.all(tasks.map(t => t.p));
    const errors = [];

    const categories = {};
    const sources = new Set();
    for (const [catKey, cat] of Object.entries(CATEGORIES)) {
      categories[catKey] = { label: cat.label, items: [] };
    }
    tasks.forEach((t, i) => {
      const r = results[i];
      if (r && typeof r.price === 'number' && r.price > 0) {
        categories[t.catKey].items.push({
          code: t.item.code,
          nameZh: t.item.nameZh,
          unit: t.item.unit,
          price: r.price,
          prevClose: r.prevClose,
          changePct: r.changePct,
          source: r.source,
          asOf: r.asOf,
        });
        sources.add(r.source);
      } else {
        categories[t.catKey].items.push({
          code: t.item.code,
          nameZh: t.item.nameZh,
          unit: t.item.unit,
          price: null,
          prevClose: null,
          changePct: null,
          source: 'none',
          asOf: null,
        });
        errors.push({ code: t.item.code, src: t.item.src });
      }
    });

    let source;
    if (sources.size === 0) source = 'none';
    else if (sources.size === 1) source = Array.from(sources)[0];
    else source = Array.from(sources).sort().join('+');

    const payload = {
      categories,
      asOf: Date.now(),
      source,
      errors: errors.length > 0 ? errors : undefined,
    };

    cache = { data: payload, expiresAt: now + CACHE_TTL_MS };
    res.status(200).json(payload);
  } catch (err) {
    console.error('[api/global-markets] unhandled error:', err);
    try {
      res.status(500).json({ error: err && err.message ? err.message : String(err) });
    } catch (_) { /* headers sent */ }
  }
}
