import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { getSortedArticleDocs } from '../utils/articles';
import { BODY_EXCERPT_LENGTH, normalizeBody, type Article } from '../utils/search';

export const prerender = true;

export const GET: APIRoute = async () => {
  const docs = getSortedArticleDocs(await getCollection('docs'));
  const index: Article[] = docs.map((doc) => ({
    slug: doc.id.replace(/\.md$/, '').replace(/\.html$/, ''),
    title: doc.data.title || doc.id,
    date: doc.date,
    body: normalizeBody(doc.body || '').slice(0, BODY_EXCERPT_LENGTH),
  }));

  return new Response(JSON.stringify(index), {
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });
};
