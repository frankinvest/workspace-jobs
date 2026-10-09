// @ts-check
import { defineConfig } from 'astro/config';
import vercel from '@astrojs/vercel';

// https://astro.build/config
// 全站静态化（SSG）：**页面仍然全部在构建时预渲染**，永久 CDN 托管。
// 2026-10-09：加 Vercel adapter **只为放行一个显式声明的 on-demand 端点**
//   （src/pages/api/dash.ts，`prerender = false`）—— 给手机端做即时数据通道。
//   output 仍是 'static'：除了那个端点，其余 223 个页面照旧是纯静态产物，
//   所以"运行时文件读取 / SSR 500"的老问题不会回来（那个端点只做一次外部 fetch + 兜底）。
export default defineConfig({
  output: 'static',
  adapter: vercel(),
  build: {
    outDir: 'dist',
  },
});
