# shared/ - 历史脚本归档目录

## ⚠️ 注意：源文件已不存在

根据 2026-06-03 排查结果:
- `~/.openclaw/workspace/shared/build_full.py` 不存在
- `~/.openclaw/workspace/shared/cdp_get_innerhtml.py` 不存在

历史上 OpenClaw cron 任务的 prompt 提示找这两个脚本, 但它们从未被创建。
实际抓取是用 OpenClaw agent 的内置 `browser` 工具完成的, 不依赖外部脚本。

## 软链接
```bash
rm -rf ~/.openclaw/workspace/shared
ln -s ~/.openclaw/workspace-jobs/shared ~/.openclaw/workspace/shared
```
