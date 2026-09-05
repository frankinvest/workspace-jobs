// Frank Portfolio Sidebar — client-side price poller + password gate.
// Loaded via <script src="/portfolio.js" type="module"> in PortfolioSidebar.astro.
// Public/ static file (not bundled by Astro) to bypass component-script bundling.
// Reads holdings from build-time DOM data-* attributes, fetches live prices from
// /api/price (Vercel serverless proxy), and renders price/position%/P&L.

const PORTFOLIO_PASSWORD = 'frank123';
const PORTFOLIO_STORAGE_KEY = 'portfolio-unlocked-v1';

const portfolioSidebar = document.querySelector('.portfolio-sidebar');
const portfolioLockBtn = document.querySelector('.portfolio-lock-btn');
const portfolioGateForm = document.getElementById('portfolio-gate-form');
const portfolioPassword = document.getElementById('portfolio-password');
const portfolioGateError = document.getElementById('portfolio-gate-error');

function isStorageAvailable() {
  try {
    const key = '__portfolio_test__';
    window.sessionStorage.setItem(key, '1');
    window.sessionStorage.removeItem(key);
    return true;
  } catch (_) {
    return false;
  }
}

function wasUnlocked() {
  if (!isStorageAvailable()) return false;
  return window.sessionStorage.getItem(PORTFOLIO_STORAGE_KEY) === '1';
}

function markUnlocked() {
  if (!isStorageAvailable()) return;
  try {
    window.sessionStorage.setItem(PORTFOLIO_STORAGE_KEY, '1');
  } catch (_) {
    // ignore storage failures; still unlock for this page view
  }
}

function unlockPortfolio() {
  if (!portfolioSidebar) return;
  portfolioSidebar.classList.remove('is-locked', 'is-gate-open');
  portfolioSidebar.classList.add('is-unlocked');
  portfolioLockBtn?.setAttribute('aria-expanded', 'false');
  if (portfolioPassword) portfolioPassword.value = '';
  if (portfolioGateError) portfolioGateError.hidden = true;
  markUnlocked();
}

function initPasswordGate() {
  if (!portfolioSidebar) return;

  if (wasUnlocked()) {
    unlockPortfolio();
    return;
  }

  portfolioLockBtn?.addEventListener('click', () => {
    const willOpen = portfolioSidebar.classList.toggle('is-gate-open');
    portfolioLockBtn.setAttribute('aria-expanded', String(willOpen));
    if (willOpen) {
      window.setTimeout(() => portfolioPassword?.focus(), 0);
    }
  });

  portfolioGateForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    if (portfolioPassword?.value === PORTFOLIO_PASSWORD) {
      unlockPortfolio();
    } else {
      if (portfolioGateError) portfolioGateError.hidden = false;
      portfolioPassword?.select();
    }
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

function fmtAmount(value) {
  if (value == null || Number.isNaN(value)) return '--';
  return `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtSignedAmount(value) {
  if (value == null || Number.isNaN(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}¥${Math.abs(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
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

function setReturnClass(el, value) {
  if (!el) return;
  el.classList.toggle('up', value > 0);
  el.classList.toggle('down', value < 0);
}

function applyStats() {
  const prices = {};
  for (const el of itemEls) {
    const code = el.getAttribute('data-code') || '';
    const raw = el.getAttribute('data-latest-price');
    prices[code] = raw == null || raw === '' ? null : parseFloat(raw);
  }

  const stats = calcHoldingStats(holdings, prices);
  const statMap = new Map(stats.map((s) => [s.code, s]));
  const maxPct = Math.max(...stats.map((s) => s.positionPct), 0);

  const totalCost = holdings.reduce((sum, h) => sum + h.shares * h.cost, 0);
  const totalValue = stats.reduce((sum, s) => sum + (s.marketValue != null ? s.marketValue : 0), 0);
  const totalPnl = totalValue - totalCost;
  const totalReturnPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;

  const totalValueEl = document.getElementById('portfolio-total-value');
  const totalPnlEl = document.getElementById('portfolio-total-pnl');
  const totalReturnEl = document.getElementById('portfolio-total-return');
  if (totalValueEl) totalValueEl.textContent = fmtAmount(totalValue);
  if (totalPnlEl) {
    totalPnlEl.textContent = fmtSignedAmount(totalPnl);
    setReturnClass(totalPnlEl, totalPnl);
  }
  if (totalReturnEl) {
    totalReturnEl.textContent = fmtPct(totalReturnPct);
    setReturnClass(totalReturnEl, totalReturnPct);
  }

  for (const el of itemEls) {
    const code = el.getAttribute('data-code') || '';
    const stat = statMap.get(code);
    if (!stat) continue;

    const priceEl = el.querySelector('[data-field="currentPrice"]');
    const pctEl = el.querySelector('[data-field="positionPct"]');
    const barEl = el.querySelector('[data-field="positionBar"]');
    const retEl = el.querySelector('[data-field="returnPct"]');
    const pnlEl = el.querySelector('[data-field="pnlAmount"]');

    if (priceEl) priceEl.textContent = fmtPrice(stat.currentPrice);
    if (pctEl) pctEl.textContent = fmtPct(stat.positionPct);
    if (barEl) {
      const width = maxPct > 0 ? (stat.positionPct / maxPct) * 100 : 0;
      barEl.style.width = `${width.toFixed(2)}%`;
    }
    if (retEl) {
      retEl.textContent = fmtPct(stat.returnPct);
      setReturnClass(retEl, stat.returnPct);
    }
    if (pnlEl) {
      const pnl = stat.marketValue != null ? stat.marketValue - stat.shares * stat.cost : null;
      pnlEl.textContent = fmtSignedAmount(pnl);
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

initPasswordGate();

if (codes.length > 0) {
  startPricePolling(codes, handleResponse, 60000);
}
