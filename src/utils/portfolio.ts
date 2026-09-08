/**
 * Portfolio calculation utilities.
 *
 * Build-time:
 *   - parseFrankInput() — convert Frank's natural-language input to Holding
 *   - calcHoldingStats() — given holdings + current prices, compute market value / position % / return %
 *
 * Used by:
 *   - src/components/PortfolioSidebar.astro (build-time skeleton + client-side refresh)
 *   - tools/parse_holding.py → Frank input parser
 *   - tests/unit/portfolio.test.ts (vitest)
 *
 * Design: pure functions, no side effects, vitest-friendly.
 */

export interface Holding {
  /** Stock code, e.g. "600015" (上交所), "000001" (深交所), "300750" (创业板) */
  code: string;
  /** Chinese name, e.g. "华夏银行" */
  name: string;
  /** Number of shares held */
  shares: number;
  /** Average cost per share, in CNY */
  cost: number;
}

export interface PriceSnapshot {
  /** Latest price in CNY */
  currentPrice: number;
  /** Previous trading-day close in CNY (may be null if source didn't return it) */
  prevClose: number | null;
}

export interface HoldingStats extends Holding {
  /** Latest price in CNY, or null if price unavailable */
  currentPrice: number | null;
  /** Previous trading-day close in CNY (paired with currentPrice), null if unknown */
  prevClose: number | null;
  /** shares × currentPrice, or null if price unavailable */
  marketValue: number | null;
  /** Position percentage (0-100), equal weight if all prices null */
  positionPct: number;
  /** Return percentage vs cost (signed), 0 if no price */
  returnPct: number;
  /** Today's return percentage vs prev close (signed), 0 if no price or no prev close */
  todayReturnPct: number;
}

/**
 * Parse Frank's natural-language holding input.
 * Expected format: "<name> <shares> <cost>"
 *
 * Examples:
 *   "华夏银行 45100 6.504" → {name: "华夏银行", shares: 45100, cost: 6.504}
 *   "招商银行  1000  38.50" → {name: "招商银行", shares: 1000, cost: 38.50}
 *   "中  国  神  华  100  26.5" → trimmed, OK
 *
 * Returns null on invalid input (does not throw — caller decides fallback).
 *
 * Note: parser does NOT look up the stock code. Code lookup happens server-side
 * via tools/parse_holding.py (uses akshare, not bundled in Vercel lambda).
 */
export function parseFrankInput(text: string): { name: string; shares: number; cost: number } | null {
  if (!text || typeof text !== 'string') return null;
  const trimmed = text.trim().replace(/\s+/g, ' ');
  // Capture: Chinese name (no digits) + space + integer shares + space + decimal cost
  // Chinese name can include 中文/英文/数字字母混合 but not standalone digits at the end
  const match = trimmed.match(/^([^\d]+?)\s+(\d+)\s+([\d.]+)$/);
  if (!match) return null;
  const [, name, sharesStr, costStr] = match;
  const name_ = (name || '').trim();
  const shares = parseInt(sharesStr, 10);
  const cost = parseFloat(costStr);
  if (!name_ || isNaN(shares) || isNaN(cost) || shares <= 0 || cost <= 0) return null;
  return { name: name_, shares, cost };
}

/**
 * Calculate holding statistics with current prices (and optional prev close).
 *
 * Prices input shape (per code):
 *   - number  → legacy: currentPrice only (prevClose null)
 *   - { currentPrice, prevClose } → full snapshot
 *   - null    → price unknown
 *
 * - marketValue: shares × currentPrice (null if price missing)
 * - positionPct: marketValue / totalMarketValue × 100 (0 if no prices at all → equal weight)
 * - returnPct: (currentPrice - cost) / cost × 100 (0 if no price)
 * - todayReturnPct: (currentPrice - prevClose) / prevClose × 100 (0 if no price or prevClose)
 *
 * Sorted by marketValue desc (null marketValue last).
 * Holdings with null prices get positionPct=0 (or equal share if all null), returnPct=0,
 * prevClose=null, todayReturnPct=0.
 */
export function calcHoldingStats(
  holdings: Holding[],
  prices: Record<string, number | PriceSnapshot | null>,
): HoldingStats[] {
  // Compute raw values per holding
  const computed: HoldingStats[] = holdings.map(h => {
    const raw = prices[h.code];
    const snap = normalizePriceSnapshot(raw);
    const price = snap ? snap.currentPrice : null;
    const prevClose = snap ? snap.prevClose : null;
    const marketValue = price != null ? h.shares * price : null;
    return {
      ...h,
      currentPrice: price,
      prevClose,
      marketValue,
      positionPct: 0,
      returnPct: price != null ? ((price - h.cost) / h.cost) * 100 : 0,
      todayReturnPct:
        price != null && prevClose != null && prevClose > 0
          ? ((price - prevClose) / prevClose) * 100
          : 0,
    };
  });
  // Total market value (only those with prices)
  const total = computed.reduce((sum, h) => sum + (h.marketValue ?? 0), 0);
  if (total > 0) {
    for (const h of computed) {
      if (h.marketValue != null) {
        h.positionPct = (h.marketValue / total) * 100;
      }
    }
  } else {
    // All prices null → equal weight fallback (so the UI isn't all 0)
    const equalPct = computed.length > 0 ? 100 / computed.length : 0;
    for (const h of computed) {
      h.positionPct = equalPct;
    }
  }
  // Sort by marketValue desc (null marketValue at the bottom)
  computed.sort((a, b) => {
    if (a.marketValue == null && b.marketValue == null) return 0;
    if (a.marketValue == null) return 1;
    if (b.marketValue == null) return -1;
    return b.marketValue - a.marketValue;
  });
  return computed;
}

/**
 * Normalize the per-code price entry into a PriceSnapshot | null.
 * Accepts either:
 *   - legacy `number` (currentPrice only)
 *   - `{ currentPrice, prevClose }`
 *   - null
 */
function normalizePriceSnapshot(
  raw: number | PriceSnapshot | null | undefined,
): PriceSnapshot | null {
  if (raw == null) return null;
  if (typeof raw === 'number') {
    return raw > 0 ? { currentPrice: raw, prevClose: null } : null;
  }
  if (typeof raw === 'object' && typeof raw.currentPrice === 'number' && raw.currentPrice > 0) {
    return {
      currentPrice: raw.currentPrice,
      prevClose:
        typeof raw.prevClose === 'number' && raw.prevClose > 0 ? raw.prevClose : null,
    };
  }
  return null;
}

/**
 * Account-level today's return percentage (weighted by yesterday's market value).
 * = Σ(shares × (currentPrice - prevClose)) / Σ(shares × prevClose) × 100
 *
 * Returns 0 when no holding has both currentPrice and prevClose.
 */
export function accountTodayReturnPct(stats: HoldingStats[]): number {
  let todayPnlAbs = 0;
  let yesterdayValue = 0;
  for (const s of stats) {
    if (
      s.currentPrice != null &&
      s.prevClose != null &&
      s.prevClose > 0 &&
      s.currentPrice > 0
    ) {
      todayPnlAbs += s.shares * (s.currentPrice - s.prevClose);
      yesterdayValue += s.shares * s.prevClose;
    }
  }
  if (yesterdayValue <= 0) return 0;
  return (todayPnlAbs / yesterdayValue) * 100;
}

/**
 * Account-level today's absolute P&L (sum of (current - prev) × shares).
 * Returns 0 when no holding has both prices.
 */
export function accountTodayPnlAbs(stats: HoldingStats[]): number {
  let sum = 0;
  for (const s of stats) {
    if (s.currentPrice != null && s.prevClose != null && s.prevClose > 0 && s.currentPrice > 0) {
      sum += s.shares * (s.currentPrice - s.prevClose);
    }
  }
  return sum;
}

// ── Display formatters ────────────────────────────────────────────

/** Format percentage with sign: +5.23% / -2.10% / 0.00% */
export function fmtPct(pct: number): string {
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

/** Format price: 38.76 or '--' if null */
export function fmtPrice(price: number | null): string {
  return price != null ? price.toFixed(2) : '--';
}