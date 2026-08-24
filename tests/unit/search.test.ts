import { describe, it, expect } from 'vitest';
import {
  searchArticles,
  normalizeBody,
  escapeHtml,
  highlightMatches,
  isCJK,
  findAllMatches,
  extractContext,
  MIN_QUERY_LENGTH,
  MAX_QUERY_LENGTH,
  BODY_EXCERPT_LENGTH,
  SNIPPET_BEFORE,
  SNIPPET_AFTER,
  SNIPPET_MAX_COUNT,
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

describe('isCJK', () => {
  it('detects CJK characters', () => {
    expect(isCJK('今天')).toBe(true);
    expect(isCJK('早餐')).toBe(true);
    expect(isCJK('hello')).toBe(false);
    expect(isCJK('hello world')).toBe(false);
    expect(isCJK('123')).toBe(false);
  });
  it('handles mixed', () => {
    expect(isCJK('今天 hello')).toBe(true);
    expect(isCJK('hello 今天')).toBe(true);
  });
  it('handles empty', () => {
    expect(isCJK('')).toBe(false);
    expect(isCJK('   ')).toBe(false);
  });
});

describe('findAllMatches', () => {
  it('finds single match', () => {
    const matches = findAllMatches('hello world', 'world');
    expect(matches).toEqual([[6, 11]]);
  });
  it('finds multiple non-overlapping matches', () => {
    const matches = findAllMatches('foo bar foo baz foo', 'foo');
    expect(matches).toEqual([[0, 3], [8, 11], [16, 19]]);
  });
  it('is case-insensitive', () => {
    const matches = findAllMatches('Hello hello HELLO', 'hello');
    expect(matches).toEqual([[0, 5], [6, 11], [12, 17]]);
  });
  it('handles CJK', () => {
    // '今天的早餐很好, 明天早餐更好' (15 chars: 今0天1的2早3餐4很5好6,7空8明9天10早11餐12更13好14)
    // 早餐 出现在 [3,5] 和 [11,13]
    const matches = findAllMatches('今天的早餐很好, 明天早餐更好', '早餐');
    expect(matches).toEqual([[3, 5], [11, 13]]);
  });
  it('returns empty for no match', () => {
    expect(findAllMatches('hello', 'xyz')).toEqual([]);
  });
  it('returns empty for empty query', () => {
    expect(findAllMatches('hello', '')).toEqual([]);
  });
  it('returns empty for empty text', () => {
    expect(findAllMatches('', 'foo')).toEqual([]);
  });
});

describe('extractContext', () => {
  it('extracts CJK context with 10 chars each side', () => {
    // '今天天气很好非常适合出去运动打球跑步' (18 chars)
    // match '很好' at [4, 6]
    // before=10: startIdx = max(0, 4-10) = 0
    // after=10:  endIdx   = min(18, 6+10) = 16
    // context = text[0:16] = '今天天气很好非常适合出去运动打球' (16 chars: 4 before + 2 match + 10 after)
    // hasLeading = (0 > 0) = false (没东西被截掉在前面)
    // hasTrailing = (16 < 18) = true (后面还有 跑步 被截掉)
    const text = '今天天气很好非常适合出去运动打球跑步';
    const result = extractContext(text, 4, 6, 10, 10);
    expect(result.context).toBe('今天天气很好非常适合出去运动打球');
    expect(result.hasLeading).toBe(false);
    expect(result.hasTrailing).toBe(true);
  });
  it('extracts English context with word boundary', () => {
    const text = 'The quick brown fox jumps over the lazy dog in the park yesterday';
    // "fox" at position 16
    const result = extractContext(text, 16, 19, 10, 10);
    // Should be "the quick brown fox jumps over the lazy" approximately
    // (word boundary based, 10 words each side)
    expect(result.context).toContain('fox');
    expect(result.context).toContain('quick');
    expect(result.context).toContain('brown');
  });
  it('handles match at start of text', () => {
    const result = extractContext('hello world', 0, 5, 10, 10);
    expect(result.hasLeading).toBe(false);
    expect(result.context).toContain('hello');
  });
  it('handles match at end of text', () => {
    const text = 'world hello';
    const result = extractContext(text, 6, 11, 10, 10);
    expect(result.hasTrailing).toBe(false);
    expect(result.context).toContain('hello');
  });
  it('handles short text', () => {
    const result = extractContext('foo bar foo', 0, 3, 10, 10);
    expect(result.context).toBe('foo bar foo');
    expect(result.hasLeading).toBe(false);
    expect(result.hasTrailing).toBe(false);
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
    { slug: 'doc-5', title: '银行分析', body: '今天讨论银行不良率。银行股表现。银行业监管。' },
  ];

  it('returns empty array for empty / whitespace query', () => {
    expect(searchArticles(sampleArticles, '')).toEqual([]);
    expect(searchArticles(sampleArticles, '   ')).toEqual([]);
    expect(searchArticles(sampleArticles, '\n\t')).toEqual([]);
  });

  it('handles single-char queries (MIN_QUERY_LENGTH=1, no crash)', () => {
    const results = searchArticles(sampleArticles, 'a');
    expect(Array.isArray(results)).toBe(true);
  });

  it('handles 2-char query', () => {
    const results = searchArticles(sampleArticles, 'ap');
    expect(results).toEqual([]);
  });

  it('finds matches in title (case-insensitive)', () => {
    const results = searchArticles(sampleArticles, '早餐');
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

  it('does not return articles without match', () => {
    const results = searchArticles(sampleArticles, '早餐');
    results.forEach((r) => {
      expect(r.matchedTitle || r.matchedBody).toBe(true);
    });
  });

  it('preserves original article order', () => {
    const articles2: Article[] = [
      { slug: 'a', title: 'apple', body: '' },
      { slug: 'b', title: 'banana apple', body: '' },
      { slug: 'c', title: 'cherry apple pie', body: '' },
    ];
    const results2 = searchArticles(articles2, 'apple');
    expect(results2.map((r) => r.article.slug)).toEqual(['a', 'b', 'c']);
  });

  it('escapes HTML in snippets', () => {
    const xssArticles: Article[] = [
      { slug: 'xss', title: 'normal title', body: 'contains <script>alert("XSS")</script> in body' },
    ];
    const results = searchArticles(xssArticles, 'alert');
    expect(results[0].snippetsHtml[0]).not.toContain('<script>');
    expect(results[0].snippetsHtml[0]).toContain('&lt;script&gt;');
  });

  it('returns empty snippets for title-only match', () => {
    const titleOnly: Article[] = [
      { slug: 't1', title: '银行不良率分析', body: 'financial sector overview with no keyword' },
    ];
    const results = searchArticles(titleOnly, '银行');
    expect(results.length).toBe(1);
    expect(results[0].matchedTitle).toBe(true);
    expect(results[0].matchedBody).toBe(false);
    expect(results[0].matchCount).toBe(0);
    expect(results[0].snippetsHtml).toEqual([]);
  });

  it('returns up to 3 snippets for multiple matches', () => {
    const results = searchArticles(sampleArticles, '银行');
    const bankResult = results.find((r) => r.article.slug === 'doc-5');
    expect(bankResult).toBeDefined();
    // doc-5 body has "银行" 3 times
    expect(bankResult!.matchCount).toBe(3);
    expect(bankResult!.snippetsHtml.length).toBe(3);
    bankResult!.snippetsHtml.forEach((s) => {
      expect(s).toContain('<mark>银行</mark>');
    });
  });

  it('truncates snippets to first 3 if more than 3 matches', () => {
    const manyBank: Article[] = [
      {
        slug: 'many',
        title: '银行研究',
        body: '银行 银行 银行 银行 银行 银行 银行', // 7 matches
      },
    ];
    const results = searchArticles(manyBank, '银行');
    expect(results.length).toBe(1);
    expect(results[0].matchCount).toBe(7);
    expect(results[0].snippetsHtml.length).toBe(SNIPPET_MAX_COUNT);
  });

  it('snippetsHtml has context around match (10 chars CJK / 10 words English)', () => {
    const cjkArticle: Article[] = [
      { slug: 'cjk', title: '测试', body: '今天上午央行公布了最新的银行存款数据' },
    ];
    const cjkResults = searchArticles(cjkArticle, '银行');
    expect(cjkResults[0].snippetsHtml[0]).toContain('央行');
    expect(cjkResults[0].snippetsHtml[0]).toContain('<mark>银行</mark>');
    expect(cjkResults[0].snippetsHtml[0]).toContain('存款');
  });

  it('returns 1 snippet for single body match', () => {
    const singleMatch: Article[] = [
      { slug: 'one', title: 'test', body: 'some text with one match here' },
    ];
    const results = searchArticles(singleMatch, 'match');
    expect(results[0].matchCount).toBe(1);
    expect(results[0].snippetsHtml.length).toBe(1);
  });
});

describe('constants', () => {
  it('exposes expected constants', () => {
    expect(MIN_QUERY_LENGTH).toBe(1);
    expect(MAX_QUERY_LENGTH).toBe(50);
    expect(BODY_EXCERPT_LENGTH).toBe(5000);
    expect(SNIPPET_BEFORE).toBe(10);
    expect(SNIPPET_AFTER).toBe(10);
    expect(SNIPPET_MAX_COUNT).toBe(3);
  });
});