#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从完整 innerHTML 中精准提取评论区
"""
import re, sys, json

html = sys.stdin.read()

# 找到评论区开始位置（点赞栏之后的第一个 py-12 flex bt）
cmt_start = html.find('class="por px-15"')
if cmt_start == -1:
    print("评论区未找到")
    sys.exit(1)

cmt_html = html[cmt_start:]

# 提取每条评论（顶级评论以 py-12 flex bt 开头，包含用户名和时间）
# 顶级评论结构: <div class="py-12 flex bt"> ... <span class="cup mr-5">用户名</span> ... <span class="dark-9 fz-sm">时间</span> ... <span class="wpw">正文</span>
# 回复在 <div class="bgc-body px-9 py-5"> 容器内，每个回复是 <div class="my-5 tools-v-trigger por pr-60">

comments = []
# 分割顶级评论
top_cmt_pat = re.compile(r'<div class="py-12 flex bt">(.*?)(?=<div class="py-12 flex bt"|\n<div class="py-24"></div>)', re.DOTALL)
reply_pat = re.compile(r'<span class="c-primary cup">([^<]+)</span>.*?<span class="wpw">([^<]*(?:<[^>]+>[^<]*</[^>]+>)*[^<]*)</span>', re.DOTALL)
top_user_pat = re.compile(r'<span class="cup mr-5">([^<]+)</span>')
top_time_pat = re.compile(r'<span class="dark-9 fz-sm">([^<]+)</span>')
top_text_pat = re.compile(r'<span class="wpw">([^<]*(?:<[^>]+>[^<]*</[^>]+>)*[^<]*)</span>')

for m in top_cmt_pat.finditer(cmt_html):
    block = m.group(1)
    # 用户名
    u = ''
    um = top_user_pat.search(block)
    if um: u = um.group(1).strip()
    # 时间
    t = ''
    tm = top_time_pat.search(block)
    if tm: t = tm.group(1).strip()
    # 顶级评论正文
    txt = ''
    # 先找 wpw（评论正文）
    wpm = re.search(r'<span class="wpw">(.+?)</span>', block, re.DOTALL)
    if wpm:
        txt = re.sub(r'<[^>]+>', '', wpm.group(1)).strip()
        txt = txt.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
    if not txt:
        # 可能是图片评论
        imgm = re.search(r'class="mr-7 c-primary cup"><svg[^>]+></svg>\s*查看图片', block)
        if imgm:
            txt = '[图片评论]'
    if not u or not txt:
        continue
    item = {'user': u, 'time': t, 'content': txt, 'replies': []}
    # 找回复
    reply_section = re.search(r'<div class="bgc-body px-9 py-5">(.*?)</div>\s*</div>\s*</div>\s*</div>\s*</div>\s*</div>', block, re.DOTALL)
    if reply_section:
        reply_block = reply_section.group(1)
        for rm in reply_pat.finditer(reply_block):
            ru = rm.group(1).strip()
            rt = re.sub(r'<[^>]+>', '', rm.group(2)).strip()
            rt = rt.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
            if ru and rt:
                item['replies'].append({'user': ru, 'content': rt})
    comments.append(item)

print(f"提取到 {len(comments)} 条评论")
for c in comments[:3]:
    print(f"  {c['user']} ({c['time']}): {c['content'][:30]}... [{len(c['replies'])}条回复]")
print("  ...")

# 保存为 JSON
with open('/Users/frank_bot/.openclaw/workspace/comments.json', 'w', encoding='utf-8') as f:
    json.dump(comments, f, ensure_ascii=False, indent=2)
print(f"已保存到 comments.json")
