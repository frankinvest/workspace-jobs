// Frank Portfolio Sidebar — client-side price poller + collapse + P&L amount gate.
// Loaded via <script src="/portfolio.js" type="module"> in PortfolioSidebar.astro.

const PORTFOLIO_PASSWORD = 'frank123';
const PORTFOLIO_STORAGE_KEY = 'portfolio-amount-unlocked-v1';
const MASK = '***';

const portfolioSidebar = document.querySelector('.portfolio-sidebar');
const portfolioLockBtn = document.querySelector('.portfolio-lock-btn');
const portfolioCollapseBtn = document.querySelector('.portfolio-collapse-btn');
const portfolioGateForm = document.getElementById('portfolio-gate-form');
const portfolioPassword = document.getElementById('portfolio-password');
const portfolioGateError = document.getElementById('portfolio-gate-error');

let amountsUnlocked = false;

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

function wasAmountsUnlocked() {
  if (!isStorageAvailable()) return false;
  return window.sessionStorage.getItem(PORTFOLIO_STORAGE_KEY) === '1';
}

function persistAmountsUnlocked(unlocked) {
  if (!isStorageAvailable()) return;
  try {
    if (unlocked) {
      window.sessionStorage.setItem(PORTFOLIO_STORAGE_KEY, '1');
    } else {
      window.sessionStorage.removeItem(PORTFOLIO_STORAGE_KEY);
    }
  } catch (_) {
    // ignore storage failures; state still works for this page view
  }
}

function setLockButtonState() {
  if (!portfolioLockBtn) return;
  const label = portfolioLockBtn.querySelector('span');
  if (label) label.textContent = amountsUnlocked ? '隐藏盈亏金额' : '输入密码查看盈亏';
  portfolioLockBtn.setAttribute('aria-expanded', String(portfolioSidebar?.classList.contains('is-gate-open') || false));
}

function hideGate() {
  portfolioSidebar?.classList.remove('is-gate-open');
  if (portfolioLockBtn) portfolioLockBtn.setAttribute('aria-expanded', 'false');
  if (portfolioGateError) portfolioGateError.hidden = true;
  if (portfolioPassword) portfolioPassword.value = '';
}

function setAmountsUnlocked(unlocked) {
  amountsUnlocked = unlocked;
  portfolioSidebar?.classList.toggle('is-amount-locked', !unlocked);
  portfolioSidebar?.classList.toggle('is-amount-unlocked', unlocked);
  persistAmountsUnlocked(unlocked);
  hideGate();
  setLockButtonState();
  applyStats();
}

function initCollapse() {
  if (!portfolioSidebar || !portfolioCollapseBtn) return;
  portfolioCollapseBtn.addEventListener('click', () => {
    const nowCollapsed = portfolioSidebar.classList.toggle('is-collapsed');
    portfolioCollapseBtn.setAttribute('aria-expanded', String(!nowCollapsed));
  });
  const collapsed = portfolioSidebar.classList.contains('is-collapsed');
  portfolioCollapseBtn.setAttribute('aria-expanded', String(!collapsed));
}

function initAmountGate() {
  if (wasAmountsUnlocked()) {
    setAmountsUnlocked(true);
    return;
  }

  portfolioLockBtn?.addEventListener('click', () => {
    if (amountsUnlocked) {
      setAmountsUnlocked(false);
      return;
    }
    const willOpen = portfolioSidebar?.classList.toggle('is-gate-open') || false;
    portfolioLockBtn.setAttribute('aria-expanded', String(willOpen));
    if (willOpen) {
      window.setTimeout(() => portfolioPassword?.focus(), 0);
    }
  });

  portfolioGateForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    if (portfolioPassword?.value === PORTFOLIO_PASSWORD) {
      setAmountsUnlocked(true);
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
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${sign}¥${Math.abs(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// ── Price fetching ──

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

  // Reorder DOM so holdings are displayed by position share, largest first.
  const listEl = document.getElementById('portfolio-list');
  if (listEl) {
    const elByCode = new Map(itemEls.map((el) => [el.getAttribute('data-code') || '', el]));
    stats.forEach((stat) => {
      const el = elByCode.get(stat.code);
      if (el) listEl.appendChild(el);
    });
  }

  const totalCost = holdings.reduce((sum, h) => sum + h.shares * h.cost, 0);
  const totalValue = stats.reduce((sum, s) => sum + (s.marketValue != null ? s.marketValue : 0), 0);
  const totalPnl = totalValue - totalCost;
  const totalReturnPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;

  const totalValueEl = document.getElementById('portfolio-total-value');
  const totalPnlEl = document.getElementById('portfolio-total-pnl');
  const totalReturnEl = document.getElementById('portfolio-total-return');

  if (totalValueEl) {
    totalValueEl.textContent = amountsUnlocked ? fmtAmount(totalValue) : MASK;
  }
  if (totalPnlEl) {
    totalPnlEl.textContent = amountsUnlocked ? fmtSignedAmount(totalPnl) : MASK;
    setReturnClass(totalPnlEl, amountsUnlocked ? totalPnl : 0);
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
      pnlEl.textContent = amountsUnlocked ? fmtSignedAmount(pnl) : MASK;
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

initCollapse();
initAmountGate();

if (codes.length > 0) {
  startPricePolling(codes, handleResponse, 60000);
}
