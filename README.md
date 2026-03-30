# 财经早餐 📊

> 实时市场数据看板 - 由 Wind 金融数据驱动

## 🚀 快速开始

### 本地开发
```bash
cd /Users/frank_bot/.openclaw/workspace-jobs
npm run dev
```

### 数据更新
```bash
# 手动更新
node scripts/wind-market-update.cjs

# 构建部署
npm run build
```

## 📈 数据源

### Wind 金融数据
- A 股大盘指数：上证指数、深证成指、创业板指、科创 50
- 外盘指数：纳斯达克、道琼斯、标普 500、日经 225、恒生指数
- 期货：富时 A50、纳指期指、标普期指、布伦特原油、纽约黄金
- 热门个股：贵州茅台、平安银行、招商银行、中国平安、五粮液

### 更新频率
- 定时任务：每 12 小时自动更新
- 手动更新：点击页面「更新」按钮

## 📁 项目结构

```
workspace-jobs/
├── src/
│   ├── components/        # Astro 组件
│   ├── pages/
│   │   └── api/
│   │       └── update-market.ts  # 市场数据 API
│   └── data/
├── scripts/
│   └── wind-market-update.cjs  # Wind 数据更新脚本
├── public/data/
│   └── market_data.json  # 市场数据源
└── dist/
    └── data/
        └── market_data.json  # 构建输出
```

## 🔧 运维

### Cron 定时任务
```bash
# 查看任务
/cron status

# 刷新数据
/cron run market-update
```

### 数据验证
```bash
# 检查数据文件
cat public/data/market_data.json

# 测试 API
curl http://localhost:4321/api/update-market
```

## ⚠️ 注意事项

1. **Wind API 限制**: 当前使用示例数据，如需接入真实 Wind API 需要配置 API 端点
2. **本地开发**: 数据文件需要手动复制到 `dist/data/` 目录
3. **Vercel 部署**: 确保 `public/data/` 目录包含最新数据

## 📞 联系

- Frank: Telegram @lick789
- 时区：Asia/Shanghai (GMT+8)
