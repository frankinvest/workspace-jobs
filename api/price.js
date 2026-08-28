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
 * Proxies to:
 *   1. 东方财富 (push2.eastmoney.com) — primary
 *      https://push2.eastmoney.com/api/qt/stock/get?secid=1.600015&fields=f43
 *      response.data.f43 = current price × 100 (单位: 分)
 *   2. 腾讯 (qt.gtimg.cn) — fallback
 *      https://qt.gtimg.cn/q=sh600015
 *      response: v_sh600015="1~华夏银行~600015~38.76~..."
 *      split('~')[3] = price (decimal string)
 *   3. 新浪 (hq.sinajs.cn) — fallback (needs Referer)
 *      https://hq.sinajs.cn/list=sh600015
 *      response: var hq_str_sh600015="华夏银行,38.93,38.90,38.76,..."
 *      split(',')[3] = current price
 *
 * All responses are GBK-encoded. Must decode('gbk').
 *
 * Per MEMORY 6/11 v3: 腾讯 + 新浪 都用 native fetch (Node 18+), GBK decode,
 * 免疫 CORS (server-side fetch 不受浏览器 CORS 限制).
 *
 * Timeout: 5s per source. Total worst-case: 15s for 3 attempts.
 */

const https = require('https');
const { URL } = require('url');

const TIMEOUT_MS = 5000;
const USER_AGENT = 'Mozilla/5.0 (Jobs-Portfolio)';

// A 股代码前缀 → 市场 secid (上海=1, 深圳=0, 北交所=0)
// 上证: 6xxxxx, 9xxxxx (B 股), 5xxxxx (基金/ETF)
// 深证: 0xxxxx, 2xxxxx (B), 3xxxxx (创业板)
// 北交所: 8xxxxx, 4xxxxx
function getMarketPrefix(code) {
  if (code.startsWith('6') || code.startsWith('9') || code.startsWith('5')) return '1'; // 上海
  if (code.startsWith('8') || code.startsWith('4')) return '0'; // 北交所 (深圳 secid=0)
  return '0'; // 深圳 (含 0/2/3 开头)
}

// A 股代码 → 腾讯/新浪 prefix (sh/sz/bj)
function getTencentSinaPrefix(code) {
  if (code.startsWith('6') || code.startsWith('9') || code.startsWith('5')) return 'sh';
  if (code.startsWith('8') || code.startsWith('4')) return 'bj';
  return 'sz';
}

// ── fetchUrl helper: native https.get with timeout + optional GBK decode ──

function fetchUrl(rawUrl, headers = {}, encoding = 'utf-8') {
  return new Promise((resolve, reject) => {
    let u;
    try {
      u = new URL(rawUrl);
    } catch (err) {
      reject(new Error(`Invalid URL: ${rawUrl}`));
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
          const buf = Buffer.concat(chunks);
          if (encoding === 'gbk') {
            // Node Buffer.toString('gbk') is supported since Node 18+
            resolve(buf.toString('gbk'));
          } else {
            resolve(buf.toString('utf-8'));
          }
        });
        res.on('error', reject);
      },
    );
    req.on('timeout', () => {
      req.destroy(new Error('timeout'));
    });
    req.on('error', reject);
  });
}

// ── 3 个数据源 ──────────────────────────────────────────

async function fetchEastMoney(code) {
  const secid = `${getMarketPrefix(code)}.${code}`;
  const url = `https://push2.eastmoney.com/api/qt/stock/get?secid=${secid}&fields=f43`;
  try {
    const text = await fetchUrl(url, {
      Referer: 'https://quote.eastmoney.com/',
    });
    const json = JSON.parse(text);
    const f43 = json && json.data && json.data.f43;
    if (typeof f43 === 'number' && f43 > 0) {
      return f43 / 100; // f43 是 current price × 100
    }
    return null;
  } catch (err) {
    return null;
  }
}

async function fetchTencent(code) {
  const prefix = getTencentSinaPrefix(code);
  const url = `https://qt.gtimg.cn/q=${prefix}${code}`;
  try {
    const text = await fetchUrl(url, {}, 'gbk');
    // v_sh600015="1~华夏银行~600015~38.76~38.90~...";
    const match = text.match(/="([^"]+)"/);
    if (!match) return null;
    const parts = match[1].split('~');
    const priceStr = parts[3];
    const price = parseFloat(priceStr);
    return isNaN(price) || price <= 0 ? null : price;
  } catch (err) {
    return null;
  }
}

async function fetchSina(code) {
  const prefix = getTencentSinaPrefix(code);
  const url = `https://hq.sinajs.cn/list=${prefix}${code}`;
  try {
    const text = await fetchUrl(url, {
      Referer: 'https://finance.sina.com.cn/',
    }, 'gbk');
    // var hq_str_sh600015="华夏银行,38.93,38.90,38.76,38.90,38.61,...";
    const match = text.match(/"([^"]+)"/);
    if (!match) return null;
    const parts = match[1].split(',');
    const price = parseFloat(parts[3]);
    return isNaN(price) || price <= 0 ? null : price;
  } catch (err) {
    return null;
  }
}

async function fetchPriceWithFallback(code) {
  // 1. 东方财富 主路径
  let price = await fetchEastMoney(code);
  if (price != null) return { price, source: 'eastmoney' };
  // 2. 腾讯 fallback
  price = await fetchTencent(code);
  if (price != null) return { price, source: 'tencent' };
  // 3. 新浪 fallback
  price = await fetchSina(code);
  if (price != null) return { price, source: 'sina' };
  // 4. 全失败
  return { price: null, source: 'none' };
}

// ── Vercel serverless handler ────────────────────────────────

module.exports = async function handler(req, res) {
  // CORS for frankofswing.com (allow same-origin, no need for cross-origin)
  res.setHeader('Cache-Control', 'no-store, max-age=0');

  if (req.method !== 'GET') {
    res.status(405).json({ error: 'Method not allowed' });
    return;
  }

  // Vercel parses query string into req.query (object)
  const codesParam = (req.query && req.query.codes) || '';
  const codes = String(codesParam)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 20); // 限流: 单次最多 20 只

  if (codes.length === 0) {
    res.status(400).json({ error: 'codes param required (1-20 codes)' });
    return;
  }

  try {
    const results = await Promise.all(codes.map((c) => fetchPriceWithFallback(c)));
    const prices = {};
    let allEastmoney = true;
    let anySuccess = false;
    codes.forEach((code, i) => {
      prices[code] = results[i].price;
      if (results[i].source !== 'eastmoney') allEastmoney = false;
      if (results[i].source !== 'none') anySuccess = true;
    });
    const source = !anySuccess ? 'none' : allEastmoney ? 'eastmoney' : 'mixed';
    res.status(200).json({
      prices,
      source,
      fetchedAt: Date.now(),
    });
  } catch (err) {
    res.status(500).json({ error: String(err && err.message ? err.message : err) });
  }
};