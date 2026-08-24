/**
 * search.ts — 文章搜索工具函数
 *
 * 纯函数 (vitest 可测), 用于 frankofswing.com 搜索框:
 *   - 不区分大小写 substring 匹配
 *   - 搜 title + body (excerpt)
 *   - 边界: query < 2 字返回 [], query > 50 字截断
 *   - HTML escape 防御注入
 *   - highlightMatches() 把匹配关键词用 <mark> 包起来
 */

export interface Article {
  slug: string;
  title: string;
  date: string; // YYYYMMDD
  body: string; // 截断的 body excerpt (~200 chars)
}

export interface SearchResult {
  article: Article;
  matchedTitle: boolean;
  matchedBody: boolean;
  snippetHtml: string; // 已 HTML escape + <mark> 高亮
}

export const MIN_QUERY_LENGTH = 2;
export const MAX_QUERY_LENGTH = 50;
export const SNIPPET_RADIUS = 40;
export const BODY_EXCERPT_LENGTH = 200;

/** 把 markdown body 简化: 移除 frontmatter, 移除 markdown 标记, 截断 */
export function normalizeBody(rawBody: string): string {
  if (!rawBody) return '';
  // 去掉 frontmatter (--- ... ---)
  const fmMatch = rawBody.match(/^---\n[\s\S]*?\n---\n?([\s\S]*)$/);
  let body = fmMatch ? fmMatch[1] : rawBody;
  // 去掉 markdown 标记 (简单规则, 不追求完美)
  body = body
    .replace(/!\[[^\]]*\]\([^)]+\)/g, '') // ![alt](url) 图片
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // [text](url) 链接
    .replace(/^#{1,6}\s+/gm, '') // # 标题
    .replace(/\*\*([^*]+)\*\*/g, '$1') // **bold**
    .replace(/\*([^*]+)\*/g, '$1') // *italic*
    .replace(/`([^`]+)`/g, '$1') // `code`
    .replace(/^>\s?/gm, '') // > 引用
    .replace(/^[-*+]\s+/gm, '') // - * + 列表
    .replace(/^\d+\.\s+/gm, '') // 1. 有序列表
    .replace(/\n+/g, ' ') // 多行变一行
    .replace(/\s+/g, ' ') // 多空格合一
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

/**
 * 搜文章列表
 *
 * @param articles 文章数组 (slug + title + date + body excerpt)
 * @param query 用户输入
 * @returns 匹配结果 (按原数组顺序), 包含高亮 snippet
 */
export function searchArticles(articles: Article[], query: string): SearchResult[] {
  // 边界: 空 query / 太短 / 太长
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

    // snippet: 从 body 第一个匹配位置前后各 SNIPPET_RADIUS 字符
    let rawSnippet: string;
    if (matchedBody) {
      const idx = bodyLower.indexOf(qLower);
      const start = Math.max(0, idx - SNIPPET_RADIUS);
      const end = Math.min(article.body.length, idx + q.length + SNIPPET_RADIUS);
      rawSnippet =
        (start > 0 ? '...' : '') +
        article.body.slice(start, end).trim() +
        (end < article.body.length ? '...' : '');
    } else {
      rawSnippet = article.body.slice(0, SNIPPET_RADIUS * 2).trim() + '...';
    }

    results.push({
      article,
      matchedTitle,
      matchedBody,
      snippetHtml: highlightMatches(rawSnippet, q),
    });
  }

  return results;
}

/**
 * 在文本中找 query 出现的所有位置, 用 <mark> 包起来 (大小写不敏感, 输出 HTML escape)
 *
 * 用于 snippet 高亮 (例 "...mark达<mark>早餐</mark> 6:57 ...")
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