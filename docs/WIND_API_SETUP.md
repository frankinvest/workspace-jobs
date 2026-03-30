# 财经早餐 - Wind API 配置指南

> 如何将示例数据替换为真实的 Wind 金融数据

---

## 📋 前置条件

1. **Wind 金融数据 API 账号**
   - 需要开通 Wind API 服务
   - 获取 API Key

2. **环境变量配置**
   - 支持本地开发和生产环境配置

---

## 🚀 配置步骤

### 1. 本地开发环境

创建 `.env` 文件（如果不存在）：

```bash
cd /Users/frank_bot/.openclaw/workspace-jobs
touch .env
```

添加以下内容：

```env
WIND_API_ENABLED=true
WIND_API_KEY=your-wind-api-key-here
```

### 2. 配置 Wind API 端点

编辑 `scripts/wind-market-update.cjs`，修改 API 地址：

```javascript
const WIND_API_URL = 'https://your-wind-api-endpoint.com/v1/query';
```

### 3. 测试配置

运行脚本测试：

```bash
node scripts/wind-market-update.cjs
```

如果看到 `✅ Wind API 数据获取成功`，说明配置正确。

---

## 🌐 生产环境部署

### Vercel 环境变量配置

1. 登录 [Vercel Dashboard](https://vercel.com/dashboard)
2. 选择项目 `workspace-jobs`
3. 进入 `Settings` → `Environment Variables`
4. 添加以下变量：

| 变量名 | 值 | 环境 |
|--------|-----|------|
| `WIND_API_ENABLED` | `true` | Production, Preview, Development |
| `WIND_API_KEY` | `your-wind-api-key` | Production, Preview, Development |

5. 保存并重新部署

---

## 🔧 API 调用说明

### 请求格式

```json
POST /v1/query
{
  "queries": [
    "A 股大盘指数实时行情 上证指数 深证成指 创业板指 科创 50",
    "美股指数 纳斯达克 道琼斯 标普 500 日经 225 恒生指数",
    "期货行情 富时 A50 纳指期货 标普期指 原油 黄金",
    "个股行情 贵州茅台 平安银行 招商银行 中国平安 五粮液"
  ]
}
```

### 响应格式

```json
{
  "indices": [...],
  "usIndices": [...],
  "futures": [...],
  "stocks": [...]
}
```

---

## 🛡️ 安全措施

### 1. API Key 管理

- **不要**将 API Key 提交到 Git
- 使用环境变量管理
- 定期轮换 Key

### 2. 错误处理

脚本已实现降级策略：

```javascript
try {
  const data = await fetchWindRealtimeData();
  // 成功时使用真实数据
} catch (error) {
  console.warn('⚠️  Wind API 调用失败，降级使用示例数据');
  return getExampleData();  // 自动回退
}
```

### 3. 限流保护

如果 Wind API 有速率限制：

```bash
# 调整更新频率（默认每 12 小时）
# 编辑 vercel.json 或 cron 配置
{
  "schedule": {
    "kind": "every",
    "everyMs": 43200000  // 12 小时 = 43200000 毫秒
  }
}
```

---

## 📊 数据字段说明

### 指数/期货/个股数据结构

```typescript
{
  name: string;      // 名称（如：上证指数）
  code: string;      // 代码（如：SH000001）
  price: number;     // 最新价
  change: number;    // 涨跌额
  change_pct: number; // 涨跌幅 (%)
  high?: number;     // 最高价
  low?: number;      // 最低价
}
```

---

## 🔍 故障排查

### 问题 1: API 返回 401 错误

**原因**: API Key 无效或过期

**解决**:
1. 检查 `WIND_API_KEY` 是否正确
2. 确认 API Key 未过期
3. 重新生成 API Key

### 问题 2: 数据为空

**原因**: Wind API 查询格式不正确

**解决**:
1. 检查查询语句是否符合 Wind 语法
2. 验证股票代码是否正确
3. 查看 Wind API 文档确认格式

### 问题 3: 脚本执行失败

**原因**: Node.js 版本不兼容

**解决**:
```bash
# 检查 Node 版本
node --version  # 需要 >= 22.12.0

# 升级 Node
nvm install 22
nvm use 22
```

---

## 📞 技术支持

- **项目维护**: Frank (Telegram @lick789)
- **Wind API 支持**: 联系 Wind 官方客服
- **部署问题**: 查看 Vercel Dashboard 日志

---

## 📝 变更记录

| 日期 | 变更 | 说明 |
|------|------|------|
| 2026-03-31 | 初始版本 | 支持 Wind API 集成 |
| 2026-03-31 | 降级策略 | 添加示例数据回退机制 |

---

*文档更新时间：2026-03-31 00:45*
