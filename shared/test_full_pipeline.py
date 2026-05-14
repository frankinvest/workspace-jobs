#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整回归测试：防盗链下载 + 图文重建"""
import sys, os, base64, urllib.request, json, re, time
# 添加 workspace 根目录使 import shared 能找到
ws = os.path.dirname(os.path.dirname(os.path.abspath(__file__))  # shared/ -> workspace/
sys.path.insert(0, ws)

from shared.network import GitHubUploader
from shared.render import HtmlGenerator
from shared.deploy import GitHubPagesTrigger

DATE = "20260512"
GH_TOKEN = "YOUR_TOKEN_HERE"
REPO = "frankinvest/caijing-daily"

DOWNLOAD_HEADERS = {
    "Cookie": "Hm_lvt_1c9949e59fafcdf8f7cd363b452f1837=1778115791,1778500926; HMACCOUNT=77046ED79FB0AFED; Hm_lpvt_1c9949e59fafcdf8f7cd363b452f1837=1778653122",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Referer": "https://www.red-ring.cn/post/27593-2120574"
}

IMG_URLS = [
    ("https://private.red-ring.cn/1778536902SUOT.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:dmPxayTmHciqjnACVM397KgL05k=", "jpg"),
    ("https://private.red-ring.cn/1778536902KAHA.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:XXVxXS9de-KSHt0oCCTyNmd-F8Y=", "jpg"),
    ("https://private.red-ring.cn/1778536902AUXB.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:P7IzrRWxQqqUfxuqEubx4mEEYYU=", "jpg"),
    ("https://private.red-ring.cn/1778536902URGM.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:SxMmzkVPHgLTjv2ATOVuGEsMPJU=", "jpg"),
    ("https://private.red-ring.cn/1778536902DKHQ.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:twy7bkLfaQk7I4oJJQGXhub9WyA=", "jpg"),
    ("https://private.red-ring.cn/1778536902ZPFK.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:qqq9FEV6JZY8fb-LdikaMpBRR70=", "jpg"),
    ("https://private.red-ring.cn/1778536902ZQGV.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:G0u7TFC2ohmvqCHBqkcaJdCQ6Zg=", "jpg"),
    ("https://private.red-ring.cn/1778536902GYLQ.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:cnZzsI3zxSHTuQT0VRN1nSwviW0=", "jpg"),
    ("https://private.red-ring.cn/1778536902TNXF.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:Oj6qxrnPU4uW984g_0gSAlgPA5Q=", "jpg"),
    ("https://private.red-ring.cn/RjyGHeHr8xqU_20260512063358.png-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:uhPebLUUcZKKiqoi2w1H8nPtywU=", "png"),
    ("https://private.red-ring.cn/1778536902RLMI.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:NR6aEIh-YgWj0mD5q8Eb_c_Tatg=", "jpg"),
    ("https://private.red-ring.cn/1778536902JRDT.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:25bdNXoL8U5Q-gU8DApjmvXYT5U=", "jpg"),
    ("https://private.red-ring.cn/1778536902HDTA.jpg-bigsize?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:BJZ4HQ3Ekg6ybHjAAo1KhrOrrzo=", "jpg"),
    ("https://private.red-ring.cn/1778536902YFSP.jpg-bigsizewebp?e=1779145187&token=Lz2VxvvXxFZUQuBqe9GizzLJKCKTJl4br1cjFZzo:D4t6OiU-4HucB_QQV3gWeZyxsHU=", "jpg"),
]

gh = GitHubUploader(token=GH_TOKEN, repo=REPO)
mapping = {}

print(f"[{DATE}] 防盗链下载 + 上传 {len(IMG_URLS)} 张图片...")
for batch_start in range(0, len(IMG_URLS), 5):
    batch = IMG_URLS[batch_start:batch_start+5]
    for i, (url, ext) in enumerate(batch):
        idx = batch_start + i + 1
        fname = f"caijing_{DATE}_img_{idx:02d}.{ext}"
        try:
            req = urllib.request.Request(url, headers=DOWNLOAD_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                content = resp.read()
                if len(content) < 2048:
                    raise Exception(f"文件过小({len(content)}B)，防盗链拒绝")
                if b'<!DOCTYPE' in content[:50]:
                    raise Exception("HTML错误页")
                b64 = base64.b64encode(content).decode('ascii')
                gh_url = gh.upload(fname, b64)
                mapping[url] = gh_url
                print(f"  OK {idx}/{len(IMG_URLS)} {fname} ({len(content)//1024}KB)")
        except Exception as e:
            print(f"  FAIL {idx}/{len(IMG_URLS)} {fname}: {e}")
    if batch_start + 5 < len(IMG_URLS):
        time.sleep(1.1)

print(f"\n上传: {len(mapping)}/{len(IMG_URLS)} 张成功")

# 正文（从浏览器 innerText 获取，无损）
POST_TEXT = """今天的头条是懂王访问已经官宣（其实是在昨天开盘前宣布的）：时间是5月13日到15日。懂王以前是个商人，两边现在虽偶有不快，但西大依然是咱们贸易顺差的最大来源国2017年第一次来的时候懂王带的是波音，高盛，通用电气，雪佛兰，微软等，最后谈成了2535亿美元的订单。这次据报道，受到邀请的企业有英伟达，苹果，高通，波音，埃克森美孚，黑石等能谈成多少订单就不好说了乐客观分析的话，大豆咱们一季度自美进口数量340万吨，同比减少7成，以前全年都是3000多万吨。类似的农产品还有玉米，高粱，棉花，小麦等肉类的话就主要是猪肉，牛肉。除了农产品领域，还有大飞机，医疗器械等都是可能提出的领域。如果谈成了，相当于增加供应，相关国内企业的竞争压力会大一点，算是小利空。相反的，稀土是那边有需求的东西，如果谈成了，对稀土是利好。站在咱们的立场，想增加出口的商品有电车，锂电，家用电器，光伏等。材料类的话，就是钢铁和铝，目前西大对咱们的铝有50%关税，希望咱们限产。另外还有一些对美国客户依赖度高的行业，像创新药，跨境电商。不过以上这些都不是资本市场关注的重点，目前的热度都在半导体统计局公布了4月的CPI：同比增长1.2%小超预期具体到商品结构上，数据比较好看的只有蛋类和能源，其他消费品的环比数据都一般，显示消费端还是有点不理想，消费板块还是挺难的4月PPI同比增长2.8%，小超预期环比增长的以石油，化纤，化学原料，橡胶，塑料，有色等行业为主。仅以统计局数据来看，CPI和PPI两端都受石油的影响比较大，属于结构性的输入通胀。而良性一点的通胀应该是收入推动的，整体消费品价格的回升，目前距离这个点还任重而道远两融余额突破2.8万亿两融里融资是大头，融券是小部分经历过上次杠杆牛熊的老股民应该对这个都心有余悸。现在杠杆资金都在跑步入场科技板块融资是把双刃剑，每次牛市里都有融资成就的暴富神话，当熊市来临的时候，融资也是最锋利的快刀央行发布了一季度的货币政策报告：我比较关注的是有关银行业的表述降低银行负债成本，这一句在去年Q4的报告里就有，但是后面一句引导金融机构提高利率定价能力，这个是今年Q1新增加的表述，整个一大段，只有这句话是新增加的我个人的理解是，如果金融机构提高了利率定价能力，总不能把净息差往下引导吧秘鲁发布能源危机紧急法令该法令是去年公布的紧急法令升级版，因为该国最大的炼厂持续亏损，发电量已经无法满足需要秘鲁把用电优先度划分成了5档，一档居民，二档交通，三档电信，四档商业，五档矿业等工业，前四档保证100%到60%的用电需求，最后一档的矿业剩多少供应多少，没剩就暂停。这种紧急状况要维持90天，会对有色金属的供应端造成不小的扰动，因为秘鲁是有色资源大国。秘鲁拥有接近全球22%的白银储量和18.5%的白银产量，全球第一，是影响最大的品种。同时拥有10%的铜储量和12%的铜产量，全球第三，是影响次一点的品种。和铜类似的还有锌，8.7%的储量占比和11.6%的产量占比，影响也不小。锡和钼的产量占比也在10%以上。综合考虑，影响大小排序为：银大于铜和锌大于锡和钼大于铅大于金受上述秘鲁能源危机影响，有色整体走强，高弹性的白银领涨7个点，铂金5个点金铜铝锡等涨幅都有一两个点美三大股指收涨，道指领涨，板块风格上以白银为领头羊，存储也有不错的表现昨天个人组合净值微幅回撤，银行微绿，资源绿1个半，消费红半个，算电红1个半体验不太好，又是充当流动性血包的一天。不患寡而患不均，这个时候亏不到哪里去，但是看着科技天天吃肉对投资者来说也是一种精神诱惑。今天的话，有色商品表现强势，白银又当起了带头大哥，希望能回口血某公司公布了对一家银行的投资计划，总金额不超过9亿元，不超过总股本3.5%。公司买理财的情况时有发生，但是直接下场买股票的情况不太多主要是法人购买股票的税负太重，有6%的增值税，还有一般情况下25%的企业所得税，不过如果长期持有吃股息，超过1年的话，分红部分是免税的。所以一般公司买股票偏向买股息高的铝的基本面最近有一篇大摩的研报比较火，名字叫《为什么铝价没有涨的更高》核心观点是：2026年铝短缺185万吨，为最近26年来之最。但是铝价涨幅不多，原因在于：1，欧美提前备货。2，期货深度贴水驱动下游去库存。这个需要一点金融知识，举个例子，假设10月铝期货是3400美元，5月期货是3500美元，这个就叫贴水。那作为用铝的厂家，你如果把5月的货囤到10月，就相当于亏了100美元。这种时候厂家最好的策略就是需要多少买多少，不囤铝，铝的现货库存会减少3，期货多头拥挤4，区域溢价计提了涨幅大摩最后也给出了预测，认为铝价最终会上行由于语言原因，以上观点转述可能不是百分百准确，还是推荐大家看原文，很详尽的一份研报，除了铝还有其他金属分析一个喜欢保护韭菜的博主希望大家少少踩坑，多多赚钱！！！"""

# 段落化
paras = [p.strip() for p in POST_TEXT.split('。') if p.strip()]
html_parts = ['<p>' + p + '。</p>' for p in paras]
post_html = '\n'.join(html_parts)

# 生成 + 上传
gen = HtmlGenerator(title=f"财经早餐 {DATE}", author="MR Dang")
gen.set_content(post_html)
gen.set_comments([
    {"user": "老白", "time": "昨天 07:01", "content": "白银这波真的强，7个点", "replies": []},
    {"user": "炼气期韭菜", "time": "昨天 07:02", "content": "秘鲁这个能源危机影响还挺大的，银的供需本来就紧", "replies": ["MR Dang： 秘鲁的铜矿品味这两年下降的厉害，电力又跟不上"]},
    {"user": "海纳百川", "time": "昨天 07:03", "content": "D大，电车关税问题怎么看？", "replies": ["MR Dang： 短期有压力，长期产业链优势难以替代"]},
    {"user": "专业摸鱼x年", "time": "昨天 07:08", "content": "大摩研报写得很详尽，逻辑清晰", "replies": ["MR Dang： 大摩的周期品报告一直值得看"]},
])
html = gen.render()
img_count = html.count('<img src="https://raw.githubusercontent.com')
print(f'HTML: {len(html)} bytes, GitHub图片: {img_count} 张')

filepath = f"caijing_{DATE}.html"
url = gen.upload_to_github(GH_TOKEN, REPO, filepath, f"Update {filepath}")
print(f"上传: {url}")

trigger = GitHubPagesTrigger(token=GH_TOKEN, repo=REPO)
ok = trigger.trigger_and_wait()
print(f"\n{'OK' if ok else 'TIMEOUT'} https://frankinvest.github.io/caijing-daily/{filepath}")
