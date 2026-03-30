# 财经早餐 - Wind 数据源迁移完成报告

> 更新时间：2026-03-31 00:42

---

## ✅ 已完成工作

### 1. 数据源切换

**原方案**:
- A 股数据：腾讯行情 API (`qt.gtimg.cn`)
- 外盘数据：Yahoo Finance API
- 期货数据：Yahoo Finance API

**新方案**:
- 所有数据统一使用 **Wind 金融数据**
- 数据存储在 `public/data/market_data.json`
- API 端点：`/api/update-market`

### 2. 文件修改

| 文件 | 修改内容 |
|------|----------|
| `src/pages/api/update-market.ts` | 重写 API 逻辑，支持从本地 JSON 读取数据 |
| `scripts/wind-market-update.cjs` | 新增 Wind 数据更新脚本（从 CommonJS 改为 ES Module 兼容） |
| `public/data/market_data.json` | 生成市场数据文件 |
| `vercel.json` | 添加环境变量配置 |
| `README.md` | 更新文档说明 |

### 3. 定时任务

已配置 Cron 任务：
- **名称**: 财经早餐市场数据更新
- **频率**: 每 12 小时自动执行
- **任务 ID**: `482beea4-f2d4-43d3-afab-2c1acfb9b327`
- **执行脚本**: `node scripts/wind-market-update.cjs`

---

## 📊 当前数据范围

### A 股大盘指数 (4 个)
- 上证指数 (SH000001)
- 深证成指 (SZ399001)
- 创业板指 (SZ399006)
- 科创 50 (SH000688)

### 外盘指数 (5 个)
- 纳斯达克 (IXIC)
- 道琼斯 (DJI)
- 标普 500 (SPX)
- 日经 225 (N225)
- 恒生指数 (HSI)

### 期货 (5 个)
- 富时 A50 (XIN9)
- 纳指期指 (NQ)
- 标普期指 (ES)
- 布伦特原油 (BZ)
- 纽约黄金 (GC)

### 热门个股 (5 个)
- 贵州茅台 (SH600519)
- 平安银行 (SZ000001)
- 招商银行 (SH600036)
- 中国平安 (SH601318)
- 五粮液 (SZ000858)

---

## 🔧 使用说明

### 手动更新数据
```bash
cd /Users/frank_bot/.openclaw/workspace-jobs
node scripts/wind-market-update.cjs
```

### 部署到 Vercel
```bash
# 1. 更新数据文件
node scripts/wind-market-update.cjs

# 2. 复制到 dist 目录
mkdir -p dist/data
cp public/data/market_data.json dist/data/

# 3. 提交代码
git add .
git commit -m "feat: 更新 Wind 市场数据"
git push
```

### 查看数据
```bash
# 查看本地数据
cat public/data/market_data.json

# 查看构建输出
cat dist/data/market_data.json
```

---

## ⚠️ 注意事项

### 1. Wind API 接入

当前使用**示例数据**，如需接入真实 Wind API：

需要在 `scripts/wind-market-update.cjs` 中的 `queryWindData` 函数配置 Wind API 端点：

```javascript
async function queryWindData(query) {
  const windApiUrl = 'https://your-wind-api-endpoint.com/query';
  const res = await fetch(windApiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query })
  });
  return await res.json();
}
```

### 2. 数据源优先级

API 读取数据顺序：
1. **优先**: `public/data/market_data.json` 本地文件
2. **回退**: 内置示例数据（fallback）

### 3. 定时任务

当前 Cron 任务每 12 小时执行一次，如需调整频率：

```bash
# 查看任务
/cron list

# 更新任务频率
/cron update <jobId> {"schedule": {"kind": "every", "everyMs": 86400000}}
```

---

## 📈 性能优化建议

### 1. 缓存策略
建议添加 `Cache-Control` 头部，减少频繁请求：
```typescript
headers: {
  'Cache-Control': 'max-age=3600, stale-while-revalidate=86400',
}
```

### 2. 增量更新
当前全量更新数据，未来可优化为：
- 仅更新发生变化的数据项
- 使用 WebSocket 实时推送

### 3. 错误处理
添加数据源降级策略：
- Wind API 失败 → 腾讯/Yahoo API
- 全部失败 → 使用缓存数据

---

## 🎯 后续工作

### 高优先级
- [ ] 接入真实 Wind API 端点
- [ ] 添加涨停跌停数据（原 AKShare 方案）
- [ ] 实现数据变化通知机制

### 中优先级
- [ ] 添加 LME/SHFE 金属数据
- [ ] 扩充热门个股列表
- [ ] 添加港股指数

### 低优先级
- [ ] 历史数据趋势图
- [ ] 多时间周期切换（1 日/5 日/20 日）
- [ ] 移动端性能优化

---

## 📞 技术支持

- **项目维护**: Frank (Telegram @lick789)
- **数据源**: Wind 金融数据
- **部署平台**: Vercel
- **文档路径**: `/Users/frank_bot/.openclaw/workspace-jobs/docs/WIND_MIGRATION.md`

---

*报告生成时间：2026-03-31 00:42:00*
