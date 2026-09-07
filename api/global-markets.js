// Vercel serverless function: 全球大宗期货 + 美股/日韩指数聚合 (ESM).
//
//   GET /api/global-markets
//
// 返回 JSON:
//   {
//     "categories": {
//       "energy":       [ { code, name_zh, name_en, price, changePct, prevClose, source, asOf }, ... ],
//       "precious":     [ ... ],
//       "metals":       [ ... ],
//       "agriculture":  [ ... ],
//       "us_index":     [ ... ],
//       "asia_index":   [ ... ]
//     },
//     "asOf": 1756420800000,
//     "source": "tencent|yahoo|mixed|none",
//     "errors": [ ... ]   // 仅在 fallback 时填充
//   }
//
// 数据源策略（多源 race，Promise.race 取最快成功）：
//   1. 国内大宗期货（沪/大商/郑商所）→ qt.gtimg.cn (GBK → latin1 解析价格)
//   2. 国际期货（COMEX/NYMEX/CBOT/LME）+ 美股/亚太指数 → Yahoo Finance v8
//
// 缓存：5 分钟内存缓存（Vercel 单实例内有效）

import https from 'node:https';

const TIMEOUT_MS = 8000;
const USER_AGENT = 'Mozilla/5.0 (Jobs-GlobalMarkets)';
const CACHE_TTL_MS = 5 * 60 * 1000;

// 内存缓存（同一 Vercel 实例内有效）
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
// 分类 → 合约列表
// 字段说明：
//   code   — 数据源用的代码
//   nameZh — 中文名
//   nameEn — 英文名（备用）
//   unit   — 单位（用于前端展示）
//   src    — 'tencent' | 'yahoo'
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
      // 国内 SHFE / LME 通过 qt.gtimg.cn（nf 前缀）
      { code: 'nfCU0', nameZh: '沪铜主力',   unit: '元/吨', src: 'tencent' },
      { code: 'nfAL0', nameZh: '沪铝主力',   unit: '元/吨', src: 'tencent' },
      { code: 'nfZN0', nameZh: '沪锌主力',   unit: '元/吨', src: 'tencent' },
      { code: 'nfNI0', nameZh: '沪镍主力',   unit: '元/吨', src: 'tencent' },
      { code: 'nfSN0', nameZh: '沪锡主力',   unit: '元/吨', src: 'tencent' },
      { code: 'nfPB0', nameZh: '沪铅主力',   unit: '元/吨', src: 'tencent' },
    ],
  },
  agriculture: {
    label: '农产品',
    items: [
      // 国内
      { code: 'nfSR0', nameZh: '郑商所白糖',  unit: '元/吨', src: 'tencent' },
      { code: 'nfCF0', nameZh: '郑商所棉花',  unit: '元/吨', src: 'tencent' },
      { code: 'nfM0',  nameZh: '大商所豆粕',  unit: '元/吨', src: 'tencent' },
      { code: 'nfY0',  nameZh: '大商所豆油',  unit: '元/吨', src: 'tencent' },
      { code: 'nfP0',  nameZh: '大商所棕榈',  unit: '元/吨', src: 'tencent' },
      { code: 'nfC0',  nameZh: '大商所玉米',  unit: '元/吨', src: 'tencent' },
      { code: 'nfI0',  nameZh: '大商所铁矿',  unit: '元/吨', src: 'tencent' },
      // 国际
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
      // 腾讯 qt.gtimg.cn — Codex 2026-09-07 17:58 实测 Yahoo Finance 返 anti-bot sad-panda
      { code: 'usINX', nameZh: '标普 500',     unit: '点', src: 'tencent' },
      { code: 'usIXIC',nameZh: '纳斯达克综合', unit: '点', src: 'tencent' },
      { code: 'usDJI', nameZh: '道琼斯工业',   unit: '点', src: 'tencent' },
    ],
  },
  asia_index: {
    label: '亚太指数',
    items: [
      // 腾讯 qt.gtimg.cn — 避开 Yahoo Finance anti-bot
      { code: 'hkHSI',  nameZh: '恒生指数',  unit: '点', src: 'tencent' },
      { code: 'jpN225', nameZh: '日经 225',  unit: '点', src: 'tencent' },
      { code: 'krKOSPI',nameZh: '韩国 KOSPI',unit: '点', src: 'tencent' },
      { code: 'twTWSE', nameZh: '台湾加权',  unit: '点', src: 'tencent' },
    ],
  },
};

// ── 腾讯 qt.gtimg.cn 期货解析（GBK latin1 解码后正则切分）──
async function fetchTencentFutures(code) {
  const url = 'https://qt.gtimg.cn/q=' + code;
  try {
    const text = await fetchUrl(url, {}, 'gbk');
    if (!text) return null;
    const match = text.match(/="([^"]+)"/);
    if (!match) return null;
    const parts = match[1].split('~');
    // qt.gtimg.cn 期货返回结构：
    //   parts[0] = 中文名
    //   parts[3] = 当前价
    //   parts[4] = 昨收
    //   parts[5] = 今开
    //   parts[32] = 涨跌幅（%）
    const price = parseFloat(parts[3]);
    const prevClose = parseFloat(parts[4]);
    const changePct = parseFloat(parts[32]);
    if (isNaN(price) || price <= 0) return null;
    return {
      price: price,
      prevClose: isNaN(prevClose) ? null : prevClose,
      changePct: isNaN(changePct) ? null : changePct,
      source: 'tencent',
      asOf: Date.now(),
    };
  } catch (err) {
    return null;
  }
}

// ── 腾讯 qt.gtimg.cn 指数解析（GBK latin1 解码）──
// 返回结构与期货不同（以 usINX 为例验证）：
//   v_usINX="1~纳斯达克综合指数~IXIC.US~20804.36~..." 实际格式：
//   parts[0] = 名称中文
//   parts[1] = 代码
//   parts[2] = 当前价
//   parts[3] = 涨跌额
//   parts[4] = 涨跌幅（%）
//   parts[5] = 昨收
async function fetchTencentIndex(code) {
  const url = 'https://qt.gtimg.cn/q=' + code;
  try {
    const text = await fetchUrl(url, {}, 'gbk');
    if (!text) return null;
    const match = text.match(/="([^"]+)"/);
    if (!match) return null;
    const parts = match[1].split('~');
    // 指数返回结构：parts[2]=当前价, parts[3]=涨跌额, parts[4]=涨跌幅, parts[5]=昨收
    const price = parseFloat(parts[2]);
    const changePct = parseFloat(parts[4]);
    const prevClose = parseFloat(parts[5]);
    if (isNaN(price) || price <= 0) return null;
    return {
      price: price,
      prevClose: isNaN(prevClose) ? null : prevClose,
      changePct: isNaN(changePct) ? null : changePct,
      source: 'tencent',
      asOf: Date.now(),
    };
  } catch (err) {
    return null;
  }
}

// ── Yahoo Finance v8 chart API（免费、无需 key）──
// 文档：https://query1.finance.yahoo.com/v8/finance/chart/<symbol>?interval=1d&range=2d
// 返回结构：chart.result[0].meta.regularMarketPrice + chartMeta.chartPreviousClose + chartMeta.regularMarketChangePercent
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
    const changePct = meta.regularMarketChangePercent; // 已是百分比数字
    if (typeof price !== 'number' || price <= 0) return null;
    return {
      price: price,
      prevClose: typeof prevClose === 'number' ? prevClose : null,
      changePct: typeof changePct === 'number' ? changePct : null,
      source: 'yahoo',
      asOf: (meta.regularMarketTime ? meta.regularMarketTime * 1000 : Date.now()),
    };
  } catch (err) {
    return null;
  }
}

// ── 调度：根据 src 字段选择 fetcher ──
async function fetchOne(item) {
  if (item.src === 'tencent') {
    // 区分期货（nf 前缀）vs 指数（us/hk/jp/kr/tw 前缀）
    if (item.code.startsWith('nf')) return fetchTencentFutures(item.code);
    return fetchTencentIndex(item.code);
  }
  return fetchYahooQuote(item.code);
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

    // 缓存命中（5 分钟内复用）
    const now = Date.now();
    if (cache.data && cache.expiresAt > now) {
      res.status(200).json({ ...cache.data, cached: true });
      return;
    }

    // 并发抓所有合约（每合约单独 timeout）
    const tasks = [];
    for (const [catKey, cat] of Object.entries(CATEGORIES)) {
      for (const item of cat.items) {
        tasks.push({ catKey, item, p: fetchOne(item) });
      }
    }

    const results = await Promise.all(tasks.map(t => t.p));
    const errors = [];

    // 聚合结果
    const categories = {};
    const sources = new Set();
    for (const [catKey, cat] of Object.entries(CATEGORIES)) {
      categories[catKey] = {
        label: cat.label,
        items: [],
      };
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

    // 写缓存
    cache = { data: payload, expiresAt: now + CACHE_TTL_MS };

    res.status(200).json(payload);
  } catch (err) {
    console.error('[api/global-markets] unhandled error:', err);
    try {
      res.status(500).json({
        error: err && err.message ? err.message : String(err),
      });
    } catch (_) { /* headers sent */ }
  }
}
