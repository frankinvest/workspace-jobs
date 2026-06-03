# red-ring-scraper/ - 小红圈抓取 skill (历史归档)

## ⚠️ 注意：源目录已不存在

根据 2026-06-03 排查结果:
- `~/.openclaw/workspace/skills/red-ring-scraper/` 不存在 (无 SKILL.md, 无脚本)

## 当前方案
- OpenClaw cron 任务 RedRing-财经早餐-8AM 直接用内置 `browser` 工具抓取
- 不依赖此 skill 目录
- 保留此目录作为"未来重建"的占位符

## 软链接
```bash
rm -rf ~/.openclaw/workspace/skills/red-ring-scraper
ln -s ~/.openclaw/workspace-jobs/skills/red-ring-scraper ~/.openclaw/workspace/skills/red-ring-scraper
```
