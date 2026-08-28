// Vercel serverless function: stock price proxy (ESM).
//
//   GET /api/price?codes=600015,000001,300750
//
// Returns JSON:
//   {
//     "prices": { "600015": 7.85, "000001": null, ... },
//     "source": "eastmoney" | "tencent" | "sina" | "mixed" | "none",
//     "fetchedAt": 1756420800000
//   }
//
// Strategy: Promise.race across 3 sources per code, 2s per-source timeout,
// take first SUCCESSFUL result. Worst case 2.2s per code.
//
// Sources:
//   1. 东方财富 — push2.eastmoney.com (primary, GBK not needed)
//   2. 腾讯 — qt.gtimg.cn (GBK decode)
//   3. 新浪 — hq.sinajs.cn (GBK decode, needs Referer)

import https from 'node:https';

const TIMEOUT_MS = 2000;
const USER_AGENT = 'Mozilla/5.0 (Jobs-Portfolio)';

function marketSecid(code) {
  if (code.startsWith('6') || code.startsWith('9') || code.startsWith('5')) return '1';
  return '0';
}

function sinaPrefix(code) {
  if (code.startsWith('6') || code.startsWith('9') || code.startsWith('5')) return 'sh';
  if (code.startsWith('8') || code.startsWith('4')) return 'bj';
  return 'sz';
}

function fetchUrl(rawUrl, headers = {}, encoding = 'utf-8') {
  return new Promise((resolve, reject) => {
    let u;
    try {
      u = new URL(rawUrl);
    } catch (err) {
      reject(new Error('invalid url'));
      return;
    }
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
          try {
            const text = encoding === 'gbk' ? buf.toString('gbk') : buf.toString('utf-8');
            resolve(text);
          } catch (err) {
            reject(err);
          }
        });
        res.on('error', reject);
      },
    );
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

async function fetchEastMoney(code) {
  const secid = marketSecid(code) + '.' + code;
  const url = 'https://push2.eastmoney.com/api/qt/stock/get?secid=' + secid + '&fields=f43';
  try {
    const text = await fetchUrl(url, { Referer: 'https://quote.eastmoney.com/' });
    if (!text) return null;
    const json = JSON.parse(text);
    const f43 = json && json.data && json.data.f43;
    if (typeof f43 === 'number' && f43 > 0) return f43 / 100;
    return null;
  } catch (err) {
    return null;
  }
}

async function fetchTencent(code) {
  const prefix = sinaPrefix(code);
  const url = 'https://qt.gtimg.cn/q=' + prefix + code;
  try {
    const text = await fetchUrl(url, {}, 'gbk');
    if (!text) return null;
    const match = text.match(/="([^"]+)"/);
    if (!match) return null;
    const parts = match[1].split('~');
    const price = parseFloat(parts[3]);
    return isNaN(price) || price <= 0 ? null : price;
  } catch (err) {
    return null;
  }
}

async function fetchSina(code) {
  const prefix = sinaPrefix(code);
  const url = 'https://hq.sinajs.cn/list=' + prefix + code;
  try {
    const text = await fetchUrl(url, { Referer: 'https://finance.sina.com.cn/' }, 'gbk');
    if (!text) return null;
    const match = text.match(/"([^"]+)"/);
    if (!match) return null;
    const parts = match[1].split(',');
    const price = parseFloat(parts[3]);
    return isNaN(price) || price <= 0 ? null : price;
  } catch (err) {
    return null;
  }
}

async function fetchPriceRace(code) {
  // Wrap each source so null / error becomes a pending promise (race skips it).
  const wrapped = [
    fetchEastMoney(code).then((p) => (p != null ? { price: p, source: 'eastmoney' } : new Promise(() => {}))).catch(() => new Promise(() => {})),
    fetchTencent(code).then((p) => (p != null ? { price: p, source: 'tencent' } : new Promise(() => {}))).catch(() => new Promise(() => {})),
    fetchSina(code).then((p) => (p != null ? { price: p, source: 'sina' } : new Promise(() => {}))).catch(() => new Promise(() => {})),
  ];
  const timeoutPromise = new Promise((resolve) =>
    setTimeout(() => resolve({ price: null, source: 'none' }), TIMEOUT_MS + 200),
  );
  return Promise.race([...wrapped, timeoutPromise]);
}

export default async function handler(req, res) {
  try {
    res.setHeader('Cache-Control', 'no-store, max-age=0');
    res.setHeader('Content-Type', 'application/json; charset=utf-8');

    if (req.method !== 'GET') {
      res.status(405).json({ error: 'Method not allowed' });
      return;
    }

    const codesParam = (req.query && req.query.codes) || '';
    const codes = String(codesParam)
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 20);

    if (codes.length === 0) {
      res.status(400).json({ error: 'codes param required (1-20 codes)' });
      return;
    }

    const results = await Promise.all(codes.map((c) => fetchPriceRace(c)));
    const prices = {};
    let anySuccess = false;
    codes.forEach((code, i) => {
      prices[code] = results[i].price;
      if (results[i].source !== 'none') anySuccess = true;
    });
    const distinctSources = new Set(results.map((r) => r.source).filter((s) => s !== 'none'));
    let source;
    if (!anySuccess) source = 'none';
    else if (distinctSources.size === 1) source = Array.from(distinctSources)[0];
    else source = 'mixed';

    res.status(200).json({ prices, source, fetchedAt: Date.now() });
  } catch (err) {
    console.error('[api/price] unhandled error:', err);
    try {
      res.status(500).json({
        error: err && err.message ? err.message : String(err),
      });
    } catch (_) {
      // Headers already sent; can't change status.
    }
  }
}