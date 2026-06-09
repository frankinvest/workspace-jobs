#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从完整 innerHTML 中精准提取评论区（BeautifulSoup 工业级稳定版）
"""
import sys
import json
import os
from bs4 import BeautifulSoup

def main():
    # 1. 动态自适应本地用户路径，彻底解决硬编码用户的 FileNotFoundError 隐患
    OUTPUT_PATH = os.path.expanduser('~/.openclaw/workspace-jobs/comments.json')

    # 2. 从标准输入管道安全读取原始 HTML
    html_content = sys.stdin.read()
    if not html_content.strip():
        print("错误：输入的 HTML 源码为空，请检查上游抓取流。")
        sys.exit(1)

    soup = BeautifulSoup(html_content, 'html.parser')

    # 3. 锁定评论区大容器（使用 Lambda 兼容 class 属性顺序被打乱的极端情况）
    comment_container = soup.find(class_=lambda x: x and 'por' in x and 'px-15' in x)
    if not comment_container:
        print("评论区未找到，可能是前端特征码发生变阵。")
        sys.exit(1)

    comments = []

    # 4. 提取所有顶级评论区块（标准特征类名：py-12 flex bt）
    top_blocks = comment_container.find_all('div', class_='py-12 flex bt')

    for block in top_blocks:
        # 定位顶级评论的核心要素节点
        user_node = block.find('span', class_='cup mr-5')
        time_node = block.find('span', class_='dark-9 fz-sm')
        text_node = block.find('span', class_='wpw')
        
        if not user_node:
            continue
            
        user = user_node.get_text(strip=True)
        time_str = time_node.get_text(strip=True) if time_node else ""
        
        # 文本正文与图片评论的完美向下兼容
        content = ""
        if text_node:
            content = text_node.get_text(strip=True)
        elif block.find(string=lambda s: s and '查看图片' in s):
            content = "[图片评论]"
            
        if not content:
            continue

        item = {
            'user': user,
            'time': time_str,
            'content': content,
            'replies': []
        }
        
        # 5. 精准收拢二级嵌套回复区（废除危险的“数div”正则，改用标准 DOM 树遍历）
        reply_box = block.find('div', class_='bgc-body px-9 py-5')
        if reply_box:
            # 抓取回复容器内所有带有 tools-v-trigger 特征的独立回复行
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

    # 6. 本地终端审计报告打印
    print(f"提取到 {len(comments)} 条顶级评论")
    for c in comments[:3]:
        print(f"  {c['user']} ({c['time']}): {c['content'][:30]}... [{len(c['replies'])}条回复]")
    print("  ...")

    # 7. 安全确保目录存在并持久化写入 JSON
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(comments, f, ensure_ascii=False, indent=2)
    print(f"已安全保存到: {OUTPUT_PATH}")

if __name__ == '__main__':
    main()