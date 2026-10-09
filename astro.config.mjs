// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
// 全站静态化（SSG）：所有页面在构建时预渲染，永久 CDN 托管
// 彻底消除：运行时文件读取 + SSR + node:fs + 500 错误
//
// 2026-10-09 结论：**不要为了 /api/dash 加 @astrojs/vercel adapter** ——
// 本项目的 Vercel 部署只吃 `dist`（纯静态），Build Output API 里的函数会被丢掉（实测 /api/dash 404）。
// 即时数据端点改放仓根 `api/dash.js`（和 api/price.js 一样，零配置 serverless function）。
export default defineConfig({
  output: 'static',
  build: {
    outDir: 'dist',
  },
});
