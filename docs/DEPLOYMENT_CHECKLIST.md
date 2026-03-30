# 财经早餐 - 部署检查清单

> 确保项目正确部署到 Vercel

---

## ✅ 部署前检查

### 1. 代码准备

- [ ] 所有代码已提交到 Git
- [ ] 无敏感信息（API Key）提交到仓库
- [ ] `node_modules` 已添加到 `.gitignore`
- [ ] 构建无错误

```bash
# 检查构建
npm run build

# 本地预览
npm run preview
```

### 2. 数据文件验证

- [ ] `public/data/market_data.json` 存在且有效
- [ ] `dist/data/market_data.json` 已同步
- [ ] 数据格式正确（运行 `node scripts/wind-market-update.cjs`）

### 3. 环境变量配置

**本地开发** (`.env`):
```env
WIND_API_ENABLED=false  # 本地用示例数据
WIND_API_KEY=           # 无需配置
```

**Vercel 部署**:
- [ ] `WIND_API_ENABLED` 已配置
- [ ] `WIND_API_KEY` 已配置（生产环境）
- [ ] 所有环境（Production/Preview/Development）都已配置

---

## 🚀 部署步骤

### 方式一：Git 自动部署（推荐）

```bash
# 1. 更新数据
node scripts/wind-market-update.cjs

# 2. 提交代码
git add .
git commit -m "feat: 更新市场数据 - $(date '+%Y-%m-%d %H:%M')"

# 3. 推送
git push origin main
```

Vercel 会自动检测并部署。

### 方式二：手动部署

```bash
# 1. 安装 Vercel CLI
npm i -g vercel

# 2. 登录
vercel login

# 3. 部署
cd /Users/frank_bot/.openclaw/workspace-jobs
vercel --prod
```

---

## 🔍 部署后验证

### 1. 网站访问测试

- [ ] 访问 https://workspace-jobs.vercel.app
- [ ] 页面正常加载
- [ ] 市场数据显示正常
- [ ] "更新"按钮可用

### 2. API 测试

```bash
# 测试 GET 端点
curl https://workspace-jobs.vercel.app/api/update-market

# 测试强制刷新
curl -X POST https://workspace-jobs.vercel.app/api/update-market
```

**预期响应**:
```json
{
  "success": true,
  "indices": [...],
  "usIndices": [...],
  "futures": [...],
  "stocks": [...],
  "updateTime": "2026-03-31 00:45:04",
  "dataSource": "Wind 金融数据 (本地)"
}
```

### 3. 数据同步验证

- [ ] `public/data/market_data.json` 与 API 返回一致
- [ ] 更新时间为最近
- [ ] 数据项数量正确（应包含 19 个数据项）

---

## 🐛 常见问题排查

### 问题 1: 网站 404

**原因**: Vercel 部署失败

**解决**:
1. 检查 Vercel Dashboard 的部署日志
2. 确认 `vercel.json` 配置正确
3. 查看构建错误信息

### 问题 2: API 返回 500

**原因**: 数据文件未找到

**解决**:
```bash
# 检查文件是否存在
ls -la dist/data/market_data.json

# 如果不存在，重新生成
node scripts/wind-market-update.cjs
git add public/data/market_data.json
git commit -m "fix: 更新数据文件"
git push
```

### 问题 3: 数据不更新

**原因**: Cron 任务未执行或脚本失败

**解决**:
1. 检查 Cron 任务状态：`/cron list`
2. 手动触发刷新：`/cron run market-update`
3. 查看脚本执行日志

### 问题 4: 样式/布局异常

**原因**: 构建缓存问题

**解决**:
```bash
# 清理缓存重新构建
rm -rf node_modules .astro dist
npm install
npm run build
```

---

## 📊 性能监控

### 部署后 24 小时监控

- [ ] 网站访问成功率 > 99%
- [ ] API 响应时间 < 500ms
- [ ] 数据更新成功率 = 100%

### 监控工具

- **Vercel Dashboard**: 查看访问统计
- **Cron Runs**: 检查定时任务执行情况
- **浏览器 Network**: 查看 API 响应时间

---

## 🔐 安全配置

### 1. API Key 管理

- [ ] 生产环境 API Key 已配置到 Vercel
- [ ] 未将 API Key 提交到 Git
- [ ] 定期轮换 API Key

### 2. 缓存策略

当前配置：
- 默认缓存：5 分钟
- 强制刷新：无缓存
- 适用场景：减少 API 调用次数

### 3. 限流保护

如果 Wind API 有速率限制：
- [ ] 调整 Cron 执行频率
- [ ] 增加缓存时间
- [ ] 实现请求队列

---

## 📈 优化建议

### 短期优化

1. **添加错误告警**
   - 配置 Vercel 错误监控
   - 数据更新失败时发送通知

2. **提高数据准确性**
   - 接入真实 Wind API
   - 添加数据验证逻辑

3. **改善用户体验**
   - 加载状态显示
   - 错误提示优化

### 长期优化

1. **实时数据推送**
   - 使用 WebSocket 实现实时数据
   - 减少页面刷新需求

2. **数据可视化增强**
   - 添加历史趋势图
   - 支持时间范围切换

3. **多数据源容灾**
   - 实现主备数据源切换
   - 自动降级策略

---

## 📞 联系方式

- **项目维护**: Frank (Telegram @lick789)
- **时区**: Asia/Shanghai (GMT+8)
- **最佳联系时间**: 晚上

---

*检查清单版本：1.0*
*最后更新：2026-03-31 00:45*
