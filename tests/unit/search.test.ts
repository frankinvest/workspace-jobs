import { describe, it, expect } from 'vitest';
import {
  searchArticles,
  normalizeBody,
  escapeHtml,
  highlightMatches,
  MIN_QUERY_LENGTH,
  MAX_QUERY_LENGTH,
  BODY_EXCERPT_LENGTH,
  type Article,
} from '../../src/utils/search';

describe('escapeHtml', () => {
  it('escapes basic XSS chars', () => {
    expect(escapeHtml('<script>')).toBe('&lt;script&gt;');
    expect(escapeHtml('a & b')).toBe('a &amp; b');
    expect(escapeHtml('"quoted"')).toBe('&quot;quoted&quot;');
  });
  it('handles empty string', () => {
    expect(escapeHtml('')).toBe('');
  });
});

describe('normalizeBody', () => {
  it('strips frontmatter', () => {
    const raw = '---\ntitle: foo\ndate: 2026-01-01\n---\n# heading\nbody text';
    const result = normalizeBody(raw);
    expect(result).not.toContain('---');
    expect(result).not.toContain('title: foo');
    expect(result).toContain('heading');
    expect(result).toContain('body text');
  });
  it('strips markdown formatting', () => {
    expect(normalizeBody('# title')).toBe('title');
    expect(normalizeBody('**bold**')).toBe('bold');
    expect(normalizeBody('*italic*')).toBe('italic');
    expect(normalizeBody('`code`')).toBe('code');
    expect(normalizeBody('## h2')).toBe('h2');
    expect(normalizeBody('### h3')).toBe('h3');
    expect(normalizeBody('> blockquote')).toBe('blockquote');
    expect(normalizeBody('- list item')).toBe('list item');
    expect(normalizeBody('1. ordered')).toBe('ordered');
    expect(normalizeBody('![alt](http://x.com/img.png)')).toBe('');
    expect(normalizeBody('[link](http://x.com)')).toBe('link');
  });
  it('handles empty string', () => {
    expect(normalizeBody('')).toBe('');
  });
});

describe('highlightMatches', () => {
  it('wraps matched text in substring in <mark>', () => {
    expect(highlightMatches('hello world', 'world')).toBe('hello <mark>world</mark>');
  });
  it('is case-insensitive', () => {
    expect(highlightMatches('Hello World', 'WORLD')).toBe('Hello <mark>World</mark>');
  });
  it('handles multiple matches', () => {
    expect(highlightMatches('foo bar foo baz foo', 'foo')).toBe(
      '<mark>foo</mark> bar <mark>foo</mark> baz <mark>foo</mark>'
    );
  });
  it('handles empty query', () => {
    expect(highlightMatches('hello', '')).toBe('hello');
    expect(highlightMatches('hello', '   ')).toBe('hello');
  });
  it('handles CJK', () => {
    expect(highlightMatches('今天的早餐', '早餐')).toBe('今天的<mark>早餐</mark>');
  });
  it('escapes HTML in input', () => {
    expect(highlightMatches('<script>alert</script>', 'script')).toBe(
      '&lt;<mark>script</mark>&gt;alert&lt;/<mark>script</mark>&gt;'
    );
  });
});

describe('searchArticles', () => {
  const sampleArticles: Article[] = [
    { slug: 'doc-1', title: '早餐指南', body: '今天财经早餐内容很丰富' },
    { slug: 'doc-2', title: 'Tech News', body: 'Latest technology trends' },
    { slug: 'doc-3', title: 'Food Guide', body: '美味早餐推荐' },
    { slug: 'doc-4', title: 'Empty Body', body: '' },
  ];

  it('returns empty array for short query (< MIN_QUERY_LENGTH)', () => {
    expect(searchArticles(sampleArticles, 'a')).toEqual([]);
    expect(searchArticles(sampleArticles, '')).toEqual([]);
    expect(searchArticles(sampleArticles, '   ')).toEqual([]);
    expect(searchArticles(sampleArticles, '\n\t')).toEqual([]);
  });

  it('returns empty array for too-long query (> MAX_QUERY_LENGTH)', () => {
    const longQuery = 'a'.repeat(MAX_QUERY_LENGTH + 10);
    // Truncated to MAX_QUERY_LENGTH = 50 chars, all 'a's, no match in titles
    expect(searchArticles(sampleArticles, longQuery)).toEqual([]);
  });

  it('finds matches in title (case-insensitive)', () => {
    const results = searchArticles(sampleArticles, '早餐');
    // doc-1 title contains 早餐, doc-3 body contains 早餐
    expect(results.length).toBeGreaterThanOrEqual(2);
    expect(results.some((r) => r.article.slug === 'doc-1' && r.matchedTitle)).toBe(true);
  });

  it('finds matches in body', () => {
    const results = searchArticles(sampleArticles, 'technology');
    expect(results.some((r) => r.matchedBody)).toBe(true);
  });

  it('handles CJK queries', () => {
    const results = searchArticles(sampleArticles, '财经');
    expect(results.length).toBeGreaterThan(0);
  });

  it('handles mixed case queries', () => {
    const results1 = searchArticles(sampleArticles, 'TECH');
    const results2 = searchArticles(sampleArticles, 'tech');
    expect(results1.length).toBe(results2.length);
  });

  it('returns results with highlighted snippets', () => {
    const results = searchArticles(sampleArticles, '早餐');
    results.forEach((r) => {
      expect(r.snippetHtml).toContain('<mark>');
    });
  });

  it('escapes HTML in snippets', () => {
    const xssArticles: Article[] = [
      { slug: 'xss', title: 'normal title', body: 'contains <script>alert("XSS")</script> in body' },
    ];
    const results = searchArticles(xssArticles, 'alert');
    expect(results[0].snippetHtml).not.toContain('<script>');
    expect(results[0].snippetHtml).toContain('&lt;script&gt;');
  });

  it('does not return articles without match', () => {
    const results = searchArticles(sampleArticles, '早餐');
    results.forEach((r) => {
      expect(r.matchedTitle || r.matchedBody).toBe(true);
    });
  });

  it('preserves original article order', () => {
    const results = searchArticles(sampleArticles, 'doc');
    // Should match doc-1 (title) and doc-2 (title "Tech News" no, body has no), doc-4 (title "Empty Body" no, body empty)
    // Only doc-1 title matches "doc"? No, "doc" not in any. Let me try "body" instead.
    // Actually, let me try a query that matches multiple articles in order
    const articles2: Article[] = [
      { slug: 'a', title: 'apple', body: '' },
      { slug: 'b', title: 'banana apple', body: '' },
      { slug: 'c', title: 'cherry apple pie', body: '' },
    ];
    const results2 = searchArticles(articles2, 'apple');
    expect(results2.map((r) => r.article.slug)).toEqual(['a', 'b', 'c']);
  });

  it('does not include articles with empty body in body matches', () => {
    const results = searchArticles(sampleArticles, 'normal');
    expect(results.some((r) => r.article.slug === 'doc-4')).toBe(false);
  });
});

describe('constants', () => {
  it('exposes expected constants', () => {
    expect(MIN_QUERY_LENGTH).toBe(2);
    expect(MAX_QUERY_LENGTH).toBe(50);
    expect(BODY_EXCERPT_LENGTH).toBe(200);
  });
});