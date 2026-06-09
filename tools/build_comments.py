#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从完整 innerHTML 中精准提取评论区（BS4 工业级重构版）
"""
import sys
import json
import os
from bs4 import BeautifulSoup

# 1. 安全地自适应本地路径
OUTPUT_PATH = os.path.expanduser('~/.openclaw/workspace-jobs/comments.json')

# 2. 读取标准输入
html_content = sys.stdin.read()
soup = BeautifulSoup(html_content, 'html.parser')

# 3. 锁定评论区大容器 (支持类名顺序错杂)
comment_container = soup.find(class_=lambda x: x and 'por' in x and 'px-15' in x)
if not comment_container:
    print("评论区未找到")
    sys.exit(1)

comments = []

# 4. 抓取所有顶级评论区块
top_blocks = comment_container.find_all('div', class_='py-12 flex bt')

for block in top_blocks:
    # 提取顶级评论用户与时间
    user_node = block.find('span', class_='cup mr-5')
    time_node = block.find('span', class_='dark-9 fz-sm')
    text_node = block.find('span', class_='wpw')
    
    if not user_node:
        continue
        
    user = user_node.get_text(strip=True)
    time_str = time_node.get_text(strip=True) if time_node else ""
    
    # 解析正文（兼容文本与图片评论）
    content = ""
    if text_node:
        content = text_node.get_text(strip=True)
    elif block.find(text=lambda t: t and '查看图片' in t):
        content = "[图片评论]"
        
    if not content:
        continue

    item = {
        'user': user,
        'time': time_str,
        'content': content,
        'replies': []
    }
    
    # 5. 精准提取该评论下的回复区 (抛弃脆弱的正则数div)
    reply_box = block.find('div', class_='bgc-body px-9 py-5')
    if reply_box:
        # 每个回复的标准特征行
        reply_nodes = reply_box.find_all('div', class_=lambda x: x and 'tools-v-trigger' in x)
        for r_node in reply_nodes:
            r_user_node = r_node.find('span', class_='c-primary cup')
            r_text_node = r_node.find('span', class_='wpw')
            
            if r_user_node and r_text_node:
                item['replies'].append({
                    'user': r_user_node.get_text(strip=True),
                    'content': r_text_node.get_text(strip=True)
                })
                
    comments.append(item)

# 6. 打印审计报告
print(f"提取到 {len(comments)} 条顶级评论")
for c in comments[:3]:
    print(f"  {c['user']} ({c['time']}): {c['content'][:30]}... [{len(c['replies'])}条回复]")
print("  ...")

# 7. 安全保存
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(comments, f, ensure_ascii=False, indent=2)
print(f"已安全保存到: {OUTPUT_PATH}")