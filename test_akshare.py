import os
# 强制清空所有代理环境变量
for var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'no_proxy', 'NO_PROXY']:
    os.environ.pop(var, None)

import akshare as ak
print("代理已清空，开始测试...")
df = ak.stock_zh_a_spot_em()
print(f"✅ 成功获取 {len(df)} 条A股数据")
print(df[['代码','名称','最新价','涨跌幅']].head())
