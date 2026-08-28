/**
 * Client-side price fetcher.
 *
 * Calls /api/price (Vercel serverless function) which proxies to:
 *   1. 东方财富 (push2.eastmoney.com) — primary
 *   2. 腾讯 (qt.gtimg.cn) — fallback
 *   3. 新浪 (hq.sinajs.cn) — fallback
 *
 * Server-side proxy avoids CORS issues. Client just calls same-origin /api/price.
 *
 * Polling: startPricePolling() does initial fetch + setInterval(60_000) refresh.
 * Diff-update is handled by component (applyStats overwrites textContent).
 */

export interface PriceResponse {
  /** Map of code → current price (CNY) or null if all sources failed */
  prices: Record<string, number | null>;
  /** Unix timestamp (ms) of fetch */
  fetchedAt: number;
  /** Which data source was used: 'eastmoney' | 'tencent' | 'sina' | 'mixed' | 'none' */
  source: string;
}

/**
 * Fetch current prices for a list of A-share codes.
 * Returns null prices for any failed lookup (UI shows "--").
 */
export async function fetchPrices(codes: string[]): Promise<PriceResponse> {
  if (codes.length === 0) {
    return { prices: {}, fetchedAt: Date.now(), source: 'none' };
  }
  try {
    const url = `/api/price?codes=${encodeURIComponent(codes.join(','))}`;
    const resp = await fetch(url, { cache: 'no-store' });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    return (await resp.json()) as PriceResponse;
  } catch (err) {
    // Network / parse error → all null with source='none'
    const prices: Record<string, number | null> = {};
    for (const code of codes) prices[code] = null;
    return { prices, fetchedAt: Date.now(), source: 'none' };
  }
}

/**
 * Start polling prices for the given codes.
 * Initial fetch happens immediately, then every intervalMs.
 * Returns a stop() function for cleanup (e.g., page navigation).
 */
export function startPricePolling(
  codes: string[],
  cb: (resp: PriceResponse) => void,
  intervalMs = 60_000,
): () => void {
  let stopped = false;

  async function loop(): Promise<void> {
    while (!stopped) {
      const resp = await fetchPrices(codes);
      if (!stopped) cb(resp);
      if (stopped) break;
      await new Promise<void>(r => setTimeout(r, intervalMs));
    }
  }

  // Fire-and-forget; do not block the caller on the first fetch.
  loop().catch(() => {
    /* swallow — error already returned via cb */
  });

  return () => {
    stopped = true;
  };
}