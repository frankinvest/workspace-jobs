"""
api/dividend.py — 前瞻股息率 Mock API (feature/dividend-web-ui 阶段)

⚠️ 当前为 Mock 契约：未对接 tools/dividend_calculator.py 真实计算。
   仅作为前端 /api/dividend 路由的通电桩，验证请求-响应链路。

接口契约:
  - 方法: GET
  - Query 参数:
      code  (str, 必填)  — 股票代码 (6 位) 或简称
  - 响应: application/json; charset=utf-8
      {
        "code": "600015",
        "name": "华夏银行",
        "current_price": 7.42,
        "estimated_eps": 1.95,
        "predicted_dividend_yield": "7.85%",
        "industry": "银行-商业银行",
        "qualitative_adjustment": "已触发大股东派息率历史均值纠偏修正"
      }
  - 错误响应: HTTP 4xx/5xx + { "error": "...", "code": "..." }

Vercel Python runtime 自动识别 api/*.py 暴露为 /api/<basename> 路由。
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json


# ── Mock 静态映射表 (阶段 1: 假数据; 阶段 2: 替换为 dividend_calculator.py) ──
MOCK_DB = {
    "600015": {
        "code": "600015",
        "name": "华夏银行",
        "current_price": 7.42,
        "estimated_eps": 1.95,
        "predicted_dividend_yield": "7.85%",
        "industry": "银行-商业银行",
        "qualitative_adjustment": "已触发大股东派息率历史均值纠偏修正 (近 3 年派息率均值 26.8%)",
    },
    "601398": {
        "code": "601398",
        "name": "工商银行",
        "current_price": 7.18,
        "estimated_eps": 1.06,
        "predicted_dividend_yield": "6.42%",
        "industry": "银行-国有大行",
        "qualitative_adjustment": "国有大行派息率稳定，无重大行业资本开支变动",
    },
    "002170": {
        "code": "002170",
        "name": "芭田股份",
        "current_price": 9.85,
        "estimated_eps": 0.45,
        "predicted_dividend_yield": "4.12%",
        "industry": "化工-复合肥",
        "qualitative_adjustment": "已识别高派息率倾向 (近 3 年均值 60%), 行业周期底部需谨慎外推",
    },
    "601319": {
        "code": "601319",
        "name": "中国人保",
        "current_price": 6.55,
        "estimated_eps": 0.85,
        "predicted_dividend_yield": "5.18%",
        "industry": "非银金融-保险",
        "qualitative_adjustment": "财险行业派息率稳定, IFRS17 切换后利润释放节奏需观察",
    },
}

# 简称 → 代码 模糊匹配
NAME_TO_CODE = {
    "华夏银行": "600015",
    "工行": "601398",
    "工商银行": "601398",
    "芭田": "002170",
    "芭田股份": "002170",
    "人保": "601319",
    "中国人保": "601319",
}


def _mock_lookup(query: str) -> dict:
    """根据输入的 code/简称 查 Mock 表，找不到返回 fallback。"""
    q = (query or "").strip()
    if not q:
        return None

    # 1. 直接匹配代码
    if q in MOCK_DB:
        return MOCK_DB[q]

    # 2. 简称 → 代码
    code = NAME_TO_CODE.get(q)
    if code and code in MOCK_DB:
        return MOCK_DB[code]

    # 3. fallback: 任何输入都给一个"待解析"响应
    return {
        "code": q,
        "name": f"未识别标的 ({q})",
        "current_price": 0.00,
        "estimated_eps": 0.00,
        "predicted_dividend_yield": "N/A",
        "industry": "未分类",
        "qualitative_adjustment": "Mock 阶段未实现真实分类与外推逻辑",
    }


class handler(BaseHTTPRequestHandler):
    """Vercel Python serverless entrypoint."""

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        code = (qs.get("code") or qs.get("name") or [""])[0]

        if not code:
            self._respond_json(
                400,
                {
                    "error": "缺少必填参数: code (股票代码或简称)",
                    "code": "MISSING_PARAM",
                },
            )
            return

        data = _mock_lookup(code)
        self._respond_json(200, data)

    def log_message(self, format, *args):
        """静默 stderr 日志，避免污染 Vercel runtime output。"""
        return

    def _respond_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
