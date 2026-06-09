"""
api/dividend.py — 前瞻股息率 API (feature/dividend-web-ui 阶段 2)

阶段 2: 真实股票代码/名称检索 (基于 public/data/stock_index.json 全量 5500+ 沪深京股)
  - code/name 参数 → 精确/模糊匹配 stock_index.json
  - 命中: 返回真实 code + name, 量化字段 (price/eps/yield) 仍 Mock
  - 未命中: HTTP 404 + 标准错误 JSON
  - 数据更新: 跑 tools/generate_stock_index.py 重抓即可

接口契约:
  - 方法: GET
  - Query 参数:
      code  (str, 必填)  — 股票代码 (6 位或 bj+6 位) 或简称 (中文/部分)
  - 响应 (命中): 200 application/json
      {
        "code": "600015",  ← 真实匹配
        "name": "华夏银行", ← 真实匹配
        "current_price": 7.42,
        "estimated_eps": 1.95,
        "predicted_dividend_yield": "7.85%",
        "industry": "银行-商业银行",
        "qualitative_adjustment": "已触发大股东派息率历史均值纠偏修正",
        "match_type": "exact_code"  ← 新增: exact_code | exact_name | fuzzy_name
      }
  - 响应 (未命中): 404 application/json
      { "error": "未在 stock_index.json 找到匹配项", "query": "xxx", "code": "NOT_FOUND" }

Vercel Python runtime 自动识别 api/*.py 暴露为 /api/<basename> 路由。
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import os
import sys
from pathlib import Path


# ── 加载 stock_index.json (启动时一次, Vercel runtime 内存缓存) ──────────────
def _load_stock_index():
    """从 public/data/stock_index.json 加载全量股票名录

    路径优先级:
      1. <repo_root>/public/data/stock_index.json (本地开发 + Vercel Python runtime)
      2. <repo_root>/dist/data/stock_index.json (Astro build 后的产物)
    """
    candidates = [
        Path.home() / ".openclaw" / "workspace-jobs" / "public" / "data" / "stock_index.json",
        Path(__file__).parent.parent / "public" / "data" / "stock_index.json",
        Path(__file__).parent.parent / "dist" / "data" / "stock_index.json",
    ]
    for p in candidates:
        try:
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                print(f"[dividend] loaded {len(data)} stocks from {p}", file=sys.stderr)
                return data, p
        except Exception as e:
            print(f"[dividend] FAIL load {p}: {type(e).__name__}: {e}", file=sys.stderr)
    print(f"[dividend] ❌ stock_index.json not found, tried: {[str(p) for p in candidates]}", file=sys.stderr)
    return [], None


STOCK_INDEX, STOCK_INDEX_PATH = _load_stock_index()
STOCK_BY_CODE = {s["code"]: s for s in STOCK_INDEX}
STOCK_BY_NAME = {s["name"]: s for s in STOCK_INDEX}


# ── Mock 量化数据 (阶段 2 仍占位, 阶段 3 接 dividend_calculator.py) ──────────
def _mock_quant(code: str, name: str) -> dict:
    """根据股票代码前缀推测市场 + 行业, 给出合理 Mock 数据"""
    code_clean = code.replace("bj", "")
    industry = "未分类"
    if code_clean.startswith(("600", "601", "603", "605")):
        industry = "沪市主板"
    elif code_clean.startswith("688"):
        industry = "沪市科创板"
    elif code_clean.startswith(("000", "001", "002")):
        industry = "深市主板/中小板"
    elif code_clean.startswith("300"):
        industry = "深市创业板"
    elif code_clean.startswith(("83", "87", "920")):
        industry = "北交所"
    elif code_clean.startswith(("8", "4")):
        industry = "北交所"

    # 银行/保险类给个看起来合理的 yield (5-8%)
    yield_5 = "6.85%"
    return {
        "current_price": round(7.42 + (hash(code) % 100) / 10.0, 2),
        "estimated_eps": round(1.95 - (hash(code + "eps") % 100) / 100.0, 2),
        "predicted_dividend_yield": yield_5,
        "industry": industry,
        "qualitative_adjustment": f"Mock 阶段 (feature/dividend-web-ui): 命中 {len(STOCK_INDEX)} 股票库; 量化指标待对接 dividend_calculator.py",
    }


def _lookup(query: str):
    """查询股票: 精确代码 > 精确名称 > 模糊名称 (含 query 子串)

    返回 (result_dict, match_type) 或 (None, None)
    """
    q = (query or "").strip()
    if not q:
        return None, None

    # 1. 精确代码 (支持 bj 前缀)
    code_candidates = [q, q.lower(), q.upper()]
    if q.lower().startswith("bj"):
        code_candidates.append(q[2:])  # 也试 bj 前缀去掉后
    for c in code_candidates:
        if c in STOCK_BY_CODE:
            s = STOCK_BY_CODE[c]
            return (s, "exact_code")

    # 2. 精确名称
    if q in STOCK_BY_NAME:
        s = STOCK_BY_NAME[q]
        return (s, "exact_name")

    # 3. 模糊名称 (substring match)
    hits = [s for s in STOCK_INDEX if q in s["name"]]
    if len(hits) == 1:
        return (hits[0], "fuzzy_name")
    elif len(hits) > 1:
        # 多个匹配: 返回 code 最小的一个 + 标注模糊
        hits.sort(key=lambda x: x["code"])
        return (hits[0], f"fuzzy_name ({len(hits)} matches)")

    return None, None


# ── 错误响应模板 ──────────────────────────────────────────────────────────────
def _error_response(status: int, code: str, message: str, query: str = "") -> dict:
    return {
        "error": message,
        "code": code,
        "query": query,
    }


class handler(BaseHTTPRequestHandler):
    """Vercel Python serverless entrypoint."""

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        query = (qs.get("code") or qs.get("name") or [""])[0]

        if not query:
            self._respond_json(400, _error_response(
                400, "MISSING_PARAM",
                "缺少必填参数: code (股票代码或简称)",
            ))
            return

        stock, match_type = _lookup(query)
        if stock is None:
            self._respond_json(404, _error_response(
                404, "NOT_FOUND",
                f"未在 stock_index.json 找到匹配项 (库内 {len(STOCK_INDEX)} 只股票)",
                query=query,
            ))
            return

        # 命中: 拼装响应
        quant = _mock_quant(stock["code"], stock["name"])
        result = {
            "code": stock["code"],
            "name": stock["name"],
            "match_type": match_type,
            **quant,
        }
        self._respond_json(200, result)

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
