/**
 * Vercel serverless function: stock price proxy.
 *
 *   GET /api/price?codes=600015,000001,300750
 *
 * Returns JSON:
 *   {
  "prices": { "600015": 7.85, "000001": null, ... },
  "source": "eastmoney" | "tencent" | "sina" | "mixed" | "none",
  "fetchedAt": 1756420800000
  }
 *
 * Strategy: Promise.race across all 3 sources per code, 2s per-source timeout,
 * take first SUCCESSFUL result. Worst-case 2s per code (vs 6s sequential).
 *
 * Sources:
 *   1. 东方财富 — https://push2.eastmoney.com/api/qt/stock/get?secid=1.600015&fields=f43
 *      response.data.f43 = current price × 100 (单位: 分)
 *   2. 腾讯 — https://qt.gtimg.cn/q=sh600015
 *      response: v_sh600015="1~华夏银行~600015~38.76~..."; split('~')[3] = price
 *   3. 新浪 — https://hq.sinajs.cn/list=sh600015 (needs Referer)
 *      response: var hq_str_sh600015="华夏银行,38.93,38.90,38.76,..."; split(',')[3] = price
 *
 * Per MEMORY 6/11 v3: 腾讯 + 新浪 都用 native fetch, GBK decode.
 */

const https = require('https');
const { URL } = require('url');

const TIMEOUT_MS = 2000; // Per-source timeout (Promise.race → first wins)
const USER_AGENT = 'Mozilla/5.0 (Jobs-Portfolio)';

// A 股代码 → 市场 secid (上海=1, 深圳/北交所=0)
function marketSecid(code) {
  if (code.startsWith('6') || code.startsWith('9') || code.startsWith('5')) return '1';
  return '0';
}

// A 股代码 → 腾讯/新浪 prefix (sh/sz/bj)
function sinaPrefix(code) {
  if (code.startsWith('6') || code.startsWith('9') || code.startsWith('5')) return 'sh';
  if (code.startsWith('8') || code.startsWith('4')) return 'bj';
  return 'sz';
}

// ── fetchUrl: native https.get, timeout + GBK decode ──

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

// ── 3 个数据源 ──

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

// ── Race: first non-null wins, 2s ceiling per code ──

async function fetchPriceRace(code) {
  // Promise.race returns first non-rejecting result; we also need first non-null.
  const sources = [
    { name: 'eastmoney', promise: fetchEastMoney(code) },
    { name: 'tencent', promise: fetchTencent(code) },
    { name: 'sina', promise: fetchSina(code) },
  ];
  // We can't easily do "first non-null" with race (null is a value, not rejection).
  // Wrap each so null becomes a never-resolving promise (so race skips it).
  const wrapped = sources.map((s) =>
    s.promise.then((price) => {
      if (price != null) return { price, source: s.name };
      // Return a pending promise so race doesn't pick this one
      return new Promise(() => {});
    }).catch(() => new Promise(() => {})),
  );
  // Race wrapped; if all fail or return null, all promises pending → use a hard timeout
  const timeoutPromise = new Promise((resolve) =>
    setTimeout(() => resolve({ price: null, source: 'none' }), TIMEOUT_MS + 200),
  );
  const result = await Promise.race([...wrapped, timeoutPromise]);
  return result;
}

// ── Vercel handler ──

module.exports = async function handler(req, res) {
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

  try {
    // Parallel per-code (each code races its 3 sources internally)
    const results = await Promise.all(codes.map((c) => fetchPriceRace(c)));
    const prices = {};
    let allSameSource = results.length > 0 ? results[0].source : 'none';
    let anySuccess = false;
    codes.forEach((code, i) => {
      prices[code] = results[i].price;
      if (results[i].source !== 'none') anySuccess = true;
    });
    // Detect mixed: if all results came from same source, use that; else 'mixed'
    const distinctSources = new Set(results.map((r) => r.source).filter((s) => s !== 'none'));
    let source;
    if (!anySuccess) source = 'none';
    else if (distinctSources.size === 1) source = Array.from(distinctSources)[0];
    else source = 'mixed';
    res.status(200).json({ prices, source, fetchedAt: Date.now() });
  } catch (err) {
    // Should not happen since fetchPriceRace always resolves, but defensive
    res.status(500).json({
      error: err && err.message ? err.message : String(err),
    });
  }
};