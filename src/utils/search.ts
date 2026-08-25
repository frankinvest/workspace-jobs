/**
 * search.ts — 文章搜索工具函数
 *
 * 纯函数 (vitest 可测), 用于 frankofswing.com 搜索框:
 *   - 不区分大小写 substring 匹配
 *   - 搜 title + body (excerpt)
 *   - 边界: query < 1 字返回 [], query > 50 字截断
 *   - HTML escape 防御注入
 *   - highlightMatches() 把匹配关键词用 <mark> 包起来
 *   - 多 snippet: body 内每个匹配都生成上下文片段 (CJK 字符级, English word-level)
 */

export interface Article {
  slug: string;
  title: string;
  date: string; // YYYYMMDD
  body: string; // 截断的 body excerpt (~5000 chars)
}

export interface SearchResult {
  article: Article;
  matchedTitle: boolean;
  matchedBody: boolean;
  /** @deprecated use snippetsHtml[0] — kept for back-compat */
  snippetHtml: string;
  /** body 内每个匹配位置的上下文 + <mark> 高亮 (length ≤ SNIPPET_MAX_COUNT) */
  snippetsHtml: string[];
  /** body 内 query 出现总次数 (title 命中不计入) */
  matchCount: number;
}

export const MIN_QUERY_LENGTH = 1;
export const MAX_QUERY_LENGTH = 50;
export const SNIPPET_RADIUS = 40;
/** CJK snippet: 关键词前后各取多少字符 */
export const SNIPPET_BEFORE = 10;
export const SNIPPET_AFTER = 10;
/** English snippet: 关键词前后各取多少个 word */
export const SNIPPET_MAX_COUNT = 3;
// Body excerpt length for search index. Default 5000 chars covers most full articles
// (after markdown stripping). Increase if some articles have body > 5000 chars and you
// want to search the tail too. Note: larger = bigger client bundle.
export const BODY_EXCERPT_LENGTH = 5000;

/** 把 markdown body 简化: 移除 frontmatter, 移除 markdown 标记, 截断 */
export function normalizeBody(rawBody: string): string {
  if (!rawBody) return '';
  const fmMatch = rawBody.match(/^---\n[\s\S]*?\n---\n?([\s\S]*)$/);
  let body = fmMatch ? fmMatch[1] : rawBody;
  body = body
    .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^>\s?/gm, '')
    .replace(/^[-*+]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .replace(/\n+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return body;
}

/** HTML escape — 防御 XSS */
export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** 检测文本是否含 CJK 字符 (用于选字符级 vs word 级上下文截取) */
export function isCJK(text: string): boolean {
  if (!text || !text.trim()) return false;
  // CJK Unified Ideographs (U+4E00-U+9FFF) + Hiragana/Katakana (U+3040-U+30FF)
  return /[\u4E00-\u9FFF\u3040-\u30FF]/.test(text);
}

/**
 * 在 text 中找 query 出现的所有 [start, end) 位置 (不区分大小写, 不重叠)
 */
export function findAllMatches(text: string, query: string): [number, number][] {
  if (!text || !query) return [];
  const matches: [number, number][] = [];
  const tLower = text.toLowerCase();
  const qLower = query.toLowerCase();
  let from = 0;
  while (from <= tLower.length - qLower.length) {
    const idx = tLower.indexOf(qLower, from);
    if (idx === -1) break;
    matches.push([idx, idx + query.length]);
    from = idx + query.length; // 非重叠: 跳到匹配末尾之后
  }
  return matches;
}

/**
 * 截取 match 周围的上下文:
 *   - CJK: 字符级 (前后各 N 字符)
 *   - English: word 级 (前后各 N 个 word)
 *
 * 返回 { context, hasLeading, hasTrailing }
 *   - context: 截取的字符串 (前后会被 mark 包裹用于高亮)
 *   - hasLeading/hasTrailing: 文本是否在原文中被截断 (用于在 snippet 前加 '...')
 */
export function extractContext(
  text: string,
  matchStart: number,
  matchEnd: number,
  before: number,
  after: number
): { context: string; hasLeading: boolean; hasTrailing: boolean } {
  if (isCJK(text)) {
    const start = Math.max(0, matchStart - before);
    const end = Math.min(text.length, matchEnd + after);
    return {
      context: text.slice(start, end),
      hasLeading: start > 0,
      hasTrailing: end < text.length,
    };
  }

  // English: word-boundary based
  const wordRegex = /\S+/g;
  const words: { word: string; start: number; end: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = wordRegex.exec(text)) !== null) {
    words.push({ word: m[0], start: m.index, end: m.index + m[0].length });
  }
  if (words.length === 0) {
    return { context: '', hasLeading: false, hasTrailing: false };
  }

  // 找包含 match 的 word (支持 query 跨多 word 的情况)
  const firstMatchWord = words.findIndex((w) => w.start < matchEnd && w.end > matchStart);
  if (firstMatchWord === -1) {
    return { context: text.slice(matchStart, matchEnd), hasLeading: matchStart > 0, hasTrailing: matchEnd < text.length };
  }
  const lastMatchWord = words.findIndex((w, i) => i >= firstMatchWord && w.start < matchEnd && w.end > matchStart);
  // findIndex from start is wrong - use a loop
  let lastMatchWordIdx = firstMatchWord;
  for (let i = firstMatchWord; i < words.length; i++) {
    if (words[i].start < matchEnd && words[i].end > matchStart) {
      lastMatchWordIdx = i;
    } else {
      break;
    }
  }

  const startWordIdx = Math.max(0, firstMatchWord - before);
  const endWordIdx = Math.min(words.length - 1, lastMatchWordIdx + after);

  const startChar = words[startWordIdx].start;
  const endChar = words[endWordIdx].end;

  return {
    context: text.slice(startChar, endChar),
    hasLeading: startWordIdx > 0,
    hasTrailing: endWordIdx < words.length - 1,
  };
}

/**
 * 在文本中找 query 出现的所有位置, 用 <mark> 包起来 (大小写不敏感, 输出 HTML escape)
 */
export function highlightMatches(text: string, query: string): string {
  if (!text) return '';
  const escaped = escapeHtml(text);
  if (!query || query.trim().length < MIN_QUERY_LENGTH) return escaped;
  const q = query.trim().slice(0, MAX_QUERY_LENGTH);
  const qLower = q.toLowerCase();
  const escapedLower = escaped.toLowerCase();

  let result = '';
  let i = 0;
  while (i < escaped.length) {
    const idx = escapedLower.indexOf(qLower, i);
    if (idx === -1) {
      result += escaped.slice(i);
      break;
    }
    result += escaped.slice(i, idx);
    result += `<mark>${escaped.slice(idx, idx + q.length)}</mark>`;
    i = idx + q.length;
  }
  return result;
}

/**
 * 搜文章列表
 *
 * @param articles 文章数组
 * @param query 用户输入
 * @returns 匹配结果, 每个 result 含:
 *   - snippetsHtml: body 内每处匹配的上下文 (capped at SNIPPET_MAX_COUNT)
 *   - matchCount: body 内 query 总出现次数 (title 命中不计入)
 *   - snippetHtml: 第一个 snippet (back-compat)
 */
export function searchArticles(articles: Article[], query: string): SearchResult[] {
  const q = query.trim().slice(0, MAX_QUERY_LENGTH);
  if (q.length < MIN_QUERY_LENGTH) return [];

  const qLower = q.toLowerCase();
  const results: SearchResult[] = [];

  for (const article of articles) {
    const titleLower = article.title.toLowerCase();
    const bodyLower = article.body.toLowerCase();

    const matchedTitle = titleLower.includes(qLower);
    const matchedBody = bodyLower.includes(qLower);

    if (!matchedTitle && !matchedBody) continue;

    const snippetsHtml: string[] = [];
    let matchCount = 0;

    if (matchedBody) {
      const matches = findAllMatches(article.body, q);
      matchCount = matches.length;
      for (const [mStart, mEnd] of matches) {
        if (snippetsHtml.length >= SNIPPET_MAX_COUNT) break;
        const { context, hasLeading, hasTrailing } = extractContext(
          article.body,
          mStart,
          mEnd,
          SNIPPET_BEFORE,
          SNIPPET_AFTER
        );
        const withEllipsis =
          (hasLeading ? '...' : '') + context + (hasTrailing ? '...' : '');
        snippetsHtml.push(highlightMatches(withEllipsis, q));
      }
    }
    // title-only match: snippetsHtml=[] + matchCount=0 (per test spec)

    const snippetHtml = snippetsHtml[0] || '';

    results.push({
      article,
      matchedTitle,
      matchedBody,
      snippetHtml,
      snippetsHtml,
      matchCount,
    });
  }

  return results;
}