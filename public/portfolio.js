// Frank Portfolio Sidebar — client-side price poller.
// Loaded via <script src="/portfolio.js" type="module"> in PortfolioSidebar.astro.
// Public/ static file (not bundled by Astro) to bypass component-script bundling.
// Reads holdings from build-time DOM data-* attributes, fetches live prices from
// /api/price (Vercel serverless proxy), and renders price/position%/return%.

// ── Collapse / expand toggle ──
const portfolioSidebar = document.querySelector('.portfolio-sidebar');
const portfolioToggle = document.querySelector('.portfolio-toggle');
if (portfolioSidebar && portfolioToggle) {
  portfolioToggle.addEventListener('click', () => {
    const nowCollapsed = portfolioSidebar.classList.toggle('is-collapsed');
    portfolioToggle.setAttribute('aria-expanded', String(!nowCollapsed));
  });
}

// ── Helpers (inlined from src/utils/portfolio.ts for client-side use) ──

function calcHoldingStats(holdings, prices) {
  const computed = holdings.map((h) => {
    const price = prices[h.code] != null ? prices[h.code] : null;
    const marketValue = price != null ? h.shares * price : null;
    return {
      ...h,
      currentPrice: price,
      marketValue,
      positionPct: 0,
      returnPct: price != null ? ((price - h.cost) / h.cost) * 100 : 0,
    };
  });
  const total = computed.reduce((sum, h) => sum + (h.marketValue != null ? h.marketValue : 0), 0);
  if (total > 0) {
    for (const h of computed) {
      if (h.marketValue != null) h.positionPct = (h.marketValue / total) * 100;
    }
  } else {
    const equalPct = computed.length > 0 ? 100 / computed.length : 0;
    for (const h of computed) h.positionPct = equalPct;
  }
  computed.sort((a, b) => {
    if (a.marketValue == null && b.marketValue == null) return 0;
    if (a.marketValue == null) return 1;
    if (b.marketValue == null) return -1;
    return b.marketValue - a.marketValue;
  });
  return computed;
}

function fmtPct(pct) {
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

function fmtPrice(price) {
  return price != null ? price.toFixed(2) : '--';
}

// ── Price fetching (inlined from src/utils/price-fetcher.ts) ──

async function fetchPrices(codes) {
  if (codes.length === 0) {
    return { prices: {}, fetchedAt: Date.now(), source: 'none' };
  }
  try {
    const url = `/api/price?codes=${encodeURIComponent(codes.join(','))}`;
    const resp = await fetch(url, { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } catch (err) {
    const prices = {};
    for (const code of codes) prices[code] = null;
    return { prices, fetchedAt: Date.now(), source: 'none' };
  }
}

function startPricePolling(codes, cb, intervalMs) {
  if (intervalMs == null) intervalMs = 60000;
  let stopped = false;
  async function loop() {
    while (!stopped) {
      const resp = await fetchPrices(codes);
      if (!stopped) cb(resp);
      if (stopped) break;
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  }
  loop().catch(() => { /* swallow */ });
  return () => { stopped = true; };
}

// ── Main: read DOM → poll → render ──

const itemEls = Array.from(document.querySelectorAll('.portfolio-item'));
const holdings = itemEls
  .map((el) => {
    const code = el.getAttribute('data-code') || '';
    const nameEl = el.querySelector('.portfolio-name');
    const shares = parseInt(el.getAttribute('data-shares') || '0', 10);
    const cost = parseFloat(el.getAttribute('data-cost') || '0');
    return {
      code,
      name: nameEl ? nameEl.textContent || '' : '',
      shares,
      cost,
    };
  })
  .filter((h) => h.code && h.shares > 0 && h.cost > 0);

const codes = holdings.map((h) => h.code);

function applyStats() {
  const prices = {};
  for (const el of itemEls) {
    const code = el.getAttribute('data-code') || '';
    const raw = el.getAttribute('data-latest-price');
    prices[code] = raw == null || raw === '' ? null : parseFloat(raw);
  }
  const stats = calcHoldingStats(holdings, prices);
  const statMap = new Map(stats.map((s) => [s.code, s]));
  for (const el of itemEls) {
    const code = el.getAttribute('data-code') || '';
    const stat = statMap.get(code);
    if (!stat) continue;
    const priceEl = el.querySelector('[data-field="currentPrice"]');
    const pctEl = el.querySelector('[data-field="positionPct"]');
    const retEl = el.querySelector('[data-field="returnPct"]');
    if (priceEl) priceEl.textContent = fmtPrice(stat.currentPrice);
    if (pctEl) pctEl.textContent = fmtPct(stat.positionPct);
    if (retEl) {
      retEl.textContent = fmtPct(stat.returnPct);
      retEl.classList.toggle('up', stat.returnPct > 0);
      retEl.classList.toggle('down', stat.returnPct < 0);
    }
  }
}

function storePrices(prices) {
  for (const el of itemEls) {
    const code = el.getAttribute('data-code') || '';
    const p = prices[code];
    el.setAttribute('data-latest-price', p == null ? '' : String(p));
  }
}

function applyMeta(source, fetchedAt) {
  const updateEl = document.getElementById('portfolio-update');
  const sourceEl = document.getElementById('portfolio-source');
  if (updateEl) {
    const d = new Date(fetchedAt);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    updateEl.textContent = '更新于 ' + hh + ':' + mm + ':' + ss;
  }
  if (sourceEl) {
    const sourceMap = {
      eastmoney: '东方财富',
      tencent: '腾讯',
      sina: '新浪',
      mixed: '多源',
      none: '数据获取失败',
    };
    sourceEl.textContent = sourceMap[source] || source;
  }
}

function handleResponse(resp) {
  storePrices(resp.prices);
  applyStats();
  applyMeta(resp.source, resp.fetchedAt);
}

if (codes.length > 0) {
  startPricePolling(codes, handleResponse, 60000);
}
