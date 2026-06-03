// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
// 全站静态化（SSG）：所有页面在构建时预渲染，永久 CDN 托管
// 彻底消除：运行时文件读取 + SSR + node:fs + 500 错误
export default defineConfig({
  output: 'static',
  build: {
    outDir: 'dist',
  },
});
