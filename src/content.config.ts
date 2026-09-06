import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

// 今日速览 TL;DR 单条（Frank 决策#2：内容只能从当天财经早餐 docs/ 提取，无外源）
const tldrItem = z.object({
  category: z.enum(['macro', 'policy', 'anomaly', 'stock', 'fx']),
  title: z.string().min(1).max(80),
  keyNumbers: z.array(z.string()).max(3).optional(),
  articleLink: z.string().regex(/^\/docs\//, '必须以 /docs/ 开头'),
});

const docs = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './docs' }),
  schema: z.object({
    title: z.string().optional(),
    date: z.string().optional(),
    tag: z.string().optional(),
    tldr: z.array(tldrItem).length(5).optional(),
    sourceUrl: z.string().url().optional(),
    sourceTitle: z.string().optional(),
    description: z.string().optional(),
  }),
});

export const collections = { docs };
