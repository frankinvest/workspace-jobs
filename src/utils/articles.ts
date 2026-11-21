import type { CollectionEntry } from 'astro:content';

export const HOME_ARTICLE_LIMIT = 3;

const htmlFiles = import.meta.glob<string>('/docs/*.html', {
  query: '?raw',
  import: 'default',
  eager: true,
});

function getArticleDate(id: string) {
  return id.match(/(\d{8})/)?.[1] || '';
}

export function getSortedArticleDocs(markdownDocs: CollectionEntry<'docs'>[]) {
  const htmlDocs = Object.keys(htmlFiles).map((path) => {
    const id = path.split('/').pop() || '';
    const date = getArticleDate(id);
    const title = date
      ? `财经早餐 ${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`
      : '财经早餐 ';
    return { id, data: { title }, body: '' };
  });

  return [...markdownDocs, ...htmlDocs]
    .map((doc) => ({ ...doc, date: getArticleDate(doc.id) }))
    .sort((a, b) => b.date.localeCompare(a.date));
}

function getCardTitle(id: string, title?: string) {
  if (title) return title;

  const fromId = id
    .replace(/\.md$/, '')
    .replace(/^jjc-\d{8}-\d+[-_]*/i, '')
    .replace(/^\d{8}-\d+[-_]*/, '')
    .replace(/-/g, ' ')
    .trim();
  return fromId && !/^\d+$/.test(fromId)
    ? fromId
    : id.replace('.md', '').replace(/-/g, ' ');
}

function formatDate(date: string) {
  if (!date) return '';
  return `${date.slice(0, 4)}年${Number(date.slice(4, 6))}月${Number(date.slice(6, 8))}日`;
}

export function getBreakfastArticles(docs: ReturnType<typeof getSortedArticleDocs>) {
  return docs
    .filter(({ id }) => (
      id.includes('财经早餐分析') || id.includes('年报') || id.includes('原文') || id.endsWith('.html')
    ))
    .map(({ id, data, date }) => ({
      id,
      title: getCardTitle(id, data.title),
      date,
      formattedDate: formatDate(date),
      tag: '财经早餐',
    }));
}
