# 财经早餐 - 项目交接文档

> 本文档供新接手的 OpenClaw 实例使用，包含完整的项目理解、开发指南和运维手册。

---

## 📌 项目概览

### 基本信息
- **项目名称**: 财经早餐
- **网站地址**: https://workspace-jobs.vercel.app
- **Git 仓库**: 本地仓库（`/Users/frank_bot/.openclaw/workspace-jobs/.git`）
- **维护者**: Frank（OpenClaw 实例）

### 核心功能
1. **大盘指数**: A股（上证、深证、创业板、科创50）+ 外盘指数（纳斯达克、道琼斯、标普500、日经225、恒生指数等）
2. **期货期货**: 富时A50、纳指/标普/道指期货、布伦特原油、纽约黄金
3. **LME/SHFE金属**: 铜、铝、锌、镍、铅、锡等
4. **热门个股**: 茅台、平安银行、招商银行、中国平安、五粮液（含市盈率、市净率）
5. **市场概况**: 涨停/跌停数量
6. **财经早餐文章**: 宏观新闻、股票分析（从 docs/content 目录读取）

### 技术栈
| 层级 | 技术 |
|------|------|
| 框架 | Astro 6.0（SSR 模式） |
| 托管 | Vercel |
| 数据源 | 腾讯行情 API + Yahoo Finance API + AKShare |
| 构建 | Node.js >= 22.12.0 |
| 包管理 | npm |

---

## 🏗️ 项目结构

```
workspace-jobs/
├── public/
│   └── data/
│       └── market_data.json     # 市场数据（构建时生成）
├── scripts/
│   └── update_market.py         # Python 数据更新脚本
├── src/
│   ├── components/
│   │   ├── ArticleCard.astro    # 文章卡片组件
│   │   ├── MarketBoard.astro    # 大盘指数组件
│   │   ├── StockList.astro      # 个股列表组件
│   │   ├── SectionHeader.astro  # 区块标题组件
│   │   └── icons/Icon.astro    # 图标组件
│   ├── content/
│   │   └── docs/               # 财经早餐文章（Markdown）
│   ├── layouts/
│   │   └── ArticleLayout.astro # 文章布局
│   ├── pages/
│   │   ├── index.astro         # 首页
│   │   ├── api/
│   │   │   └── update-market.ts # 市场数据更新 API
│   │   └── docs/[...id].astro  # 文章详情页
│   ├── styles/
│   │   └── global.css          # 全局样式
│   └── content.config.ts       # Astro 内容集合配置
├── astro.config.mjs            # Astro 配置
├── package.json
├── package-lock.json
└── vercel.json                 # Vercel 部署配置
```

---

## 🚀 日常开发

### 本地开发
```bash
cd /Users/frank_bot/.openclaw/workspace-jobs
npm run dev       # 启动开发服务器
npm run build     # 构建生产版本
npm run preview   # 预览构建结果
```

### 数据更新
**方式一: Python 脚本（推荐用于定时任务）**
```bash
cd /Users/frank_bot/.openclaw/workspace-jobs
python3 scripts/update_market.py
```
输出文件: `public/data/market_data.json`

**方式二: 浏览器端实时更新**
- 访问网站时点击「更新」按钮
- 调用 `/api/update-market` 接口获取最新数据
- 纯前端实现，无需服务器

### 部署
```bash
cd /Users/frank_bot/.openclaw/workspace-jobs
git add .
git commit -m "描述"
git push  # Vercel 会自动部署
```

---

## 📊 数据源详解

### 腾讯行情 API
- **用途**: A股指数、个股数据
- **URL**: `https://qt.gtimg.cn/q={codes}`
- **无需 API Key**，国内直连
- **股票代码规则**: `sh`=上交所，`sz`=深交所

### Yahoo Finance API
- **用途**: 外盘指数、期货
- **URL**: `https://query1.finance.yahoo.com/v8/finance/chart/{symbol}`
- **无需 API Key**，国际可用

### AKShare
- **用途**: LME金属、SHFE金属、涨停跌停数量
- **安装**: `pip install akshare`
- **注意**: 可能需要代理才能访问

---

## 🔧 运维指南

### Cron 定时任务
**当前配置**: 每天 08:00 自动更新市场数据

**设置方法**:
1. 登录 Vercel Dashboard
2. 进入项目 → Settings → Cron Jobs
3. 添加 cron: `0 8 * * *`
4. 执行: `python3 scripts/update_market.py`

**或通过 OpenClaw cron**:
```bash
# 在 OpenClaw 中执行
/cron add "market-update" "0 8 * * *" "python3 /path/to/scripts/update_market.py"
```

### 监控要点
1. **网站可访问性**: https://workspace-jobs.vercel.app
2. **数据更新**: 检查 `public/data/market_data.json` 的更新时间
3. **API 可用性**: 腾讯行情 API 国内可访问，Yahoo Finance 需代理

---

## 🎯 待完成功能

### 高优先级
- [ ] **内容源接入**: 宏观新闻、股票分析文章（需 Frank 提供数据源）
- [ ] **涨停跌停数据**: AKShare 接口不稳定，需优化

### 中优先级
- [ ] 更多热门个股
- [ ] 港股指数
- [ ] 基金数据

### 低优先级
- [ ] 移动端优化
- [ ] 深色模式
- [ ] 数据历史图表

---

## 💡 常见问题

### Q: 数据不更新怎么办？
1. 检查 `public/data/market_data.json` 是否存在
2. 运行 `python3 scripts/update_market.py` 查看错误
3. 检查腾讯行情 API 是否可访问

### Q: 构建失败怎么办？
```bash
# 清理缓存重新安装
rm -rf node_modules package-lock.json
npm install
npm run build
```

### Q: Vercel 部署失败？
1. 检查 `vercel.json` 配置
2. 查看 Vercel Dashboard 的部署日志
3. 确保 Node.js 版本 >= 22.12.0

---

## 🛠️ 推荐安装的 Skills

### 必须安装
```bash
# 财经数据获取（AKShare）
# 工作目录已存在: ~/.openclaw/workspace-jobs/skills/aakshare

# GitHub 操作（用于 CI/CD）
clawhub install github
```

### 建议安装
```bash
# 前端开发技能
clawhub install frontend-dev

# 全栈开发技能
clawhub install fullstack-dev

# 代码调试技能
clawhub install coding-agent
```

### 可选安装
```bash
# 天气查询（用于首页问候语）
clawhub install weather

# 网页内容抓取
clawhub install summarize
```

---

## 📝 代码规范

### 文件命名
- Astro 组件: `PascalCase.astro`
- TypeScript 函数: `camelCase.ts`
- Python 脚本: `snake_case.py`

### 代码风格
- 使用 TypeScript 类型定义
- Astro 组件使用 `interface Props` 定义参数
- CSS 使用 CSS 变量（见 `global.css`）

### Git 提交规范
```
feat: 新功能
fix: 修复 bug
docs: 文档更新
style: 代码格式调整
refactor: 重构
test: 测试
```

---

## 📞 联系方式

- **Frank**: Telegram @lick789
- **时区**: Asia/Shanghai (GMT+8)
- **最佳联系时间**: 晚上

---

*最后更新: 2026-03-31*
