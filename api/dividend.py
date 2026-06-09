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

# ── 接入金融数据中心 (Stage 3 攻坚) ───────────────────────────────────────────
# 注: Vercel Python runtime 部署时会扫 api/ 目录，但 tools/ 不会被打包。
#     为避免跨目录 import 风险，FinancialDataHub 的核心逻辑 here 调 stock_index 检索
#     后在线程内复用 tools 模块。Vercel 实际仓库下应改为同一仓根.
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from tools.financial_data_hub import FinancialDataHub
    _HUB_AVAILABLE = True
except Exception as _e:
    print(f"[dividend] WARN: FinancialDataHub 不可用: {type(_e).__name__}: {_e}", file=sys.stderr)
    FinancialDataHub = None
    _HUB_AVAILABLE = False


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


# ── FinancialDataHub 启动时实例化 (Stage 3) ──────────────────────────────────
_HUB_INSTANCE = None
if _HUB_AVAILABLE:
    try:
        _HUB_INSTANCE = FinancialDataHub(verbose=False)
        print(f"[dividend] FinancialDataHub ready (Stage 3 EPS live)", file=sys.stderr)
    except Exception as _e:
        print(f"[dividend] WARN: FinancialDataHub init failed: {type(_e).__name__}: {_e}", file=sys.stderr)
        _HUB_INSTANCE = None


# ── Stage 3: 前瞻年化 EPS 动态估算 ────────────────────────────────────────────
INDUSTRY_BASE_EPS_FALLBACK = 0.5  # 行业基准兜底 (亿元/年化)


def _annualize_factor(report_period: str) -> float:
    """根据报告期 (YYYYMMDD) 判断季报位置, 返回年化系数

      - 0331 (Q1):   ×4
      - 0630 (H1):   ×2
      - 0930 (Q3):   ×4/3
      - 1231 (全年):  ×1
      - 其他/解析失败:  ×4 (默认按一季报外推)
    """
    s = str(report_period or "").strip()
    if len(s) == 8 and s.isdigit():
        mmdd = s[4:]
        if mmdd == "0331":
            return 4.0
        if mmdd == "0630":
            return 2.0
        if mmdd == "0930":
            return 4.0 / 3.0
        if mmdd == "1231":
            return 1.0
    return 4.0  # 解析失败默认按 Q1 外推


def _fetch_dynamic_eps(code: str) -> dict:
    """从 FinancialDataHub 拉取最新季报, 年化计算 estimated_eps (单位: 亿元)

    返回 dict: {
      'estimated_eps': float,          # 年化盈利 (亿元), fallback 0.5
      'report_period': str,            # 最新报告期
      'source': 'live' | 'fallback'   # 是否真数据
    }
    任何异常都走 fallback, 接口不崩
    """
    if _HUB_INSTANCE is None:
        return {"estimated_eps": INDUSTRY_BASE_EPS_FALLBACK, "report_period": "n/a", "source": "fallback"}

    try:
        q = _HUB_INSTANCE.get_latest_quarterly_profit(code)
        if not q or q.get("net_profit_billion") is None or q.get("net_profit_billion", 0) == 0:
            return {
                "estimated_eps": INDUSTRY_BASE_EPS_FALLBACK,
                "report_period": q.get("report_period", "n/a") if q else "n/a",
                "source": "fallback",
            }
        net_profit_billion = float(q["net_profit_billion"])
        factor = _annualize_factor(q.get("report_period", ""))
        annualized = round(net_profit_billion * factor, 2)
        return {
            "estimated_eps": annualized,
            "report_period": q.get("report_period", "n/a"),
            "source": "live",
        }
    except Exception as e:
        print(f"[dividend] EPS fetch fail for {code}: {type(e).__name__}: {e}", file=sys.stderr)
        return {"estimated_eps": INDUSTRY_BASE_EPS_FALLBACK, "report_period": "n/a", "source": "fallback"}


# ── 实时现价拉取 (腾讯 qt.gtimg.cn, 闪电快照, <50ms) ──────────────────────
import urllib.request
import urllib.error

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q=s_{market}{code}"


def _market_prefix(code: str) -> str:
    """根据股票代码推导市场前缀
    6 → sh (沪市主板/科创)
    0, 3 → sz (深市主板/创业)
    8, 4, 9 → bj (北交所老代码 83/87/4 + 新代码 92)
    其他 → sh (fallback, 腾讯通常接受 sh fallback)
    """
    c = code.replace("bj", "").lstrip()  # 兼容 bj920992 这种带前缀的
    if not c:
        return "sh"
    if c.startswith("6"):
        return "sh"
    if c.startswith(("0", "3")):
        return "sz"
    if c.startswith(("8", "4", "9")):
        return "bj"
    return "sh"


def _fetch_realtime_price(code: str) -> float:
    """拉取腾讯闪电快照, 返回 float 现价; 任何异常 fallback 0.0

    响应格式示例: v_s_sh600036="1~招商银行~600036~38.49~-0.01~-0.03~..."
    字段 (按 ~ 分割): [0]=status, [1]=name, [2]=code, [3]=现价, ...
    """
    market = _market_prefix(code)
    code_clean = code.replace("bj", "").lstrip()
    url = TENCENT_QUOTE_URL.format(market=market, code=code_clean)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as r:
            raw = r.read().decode("gbk", errors="replace").strip()
        if not raw or "pv_none_match" in raw or "=" not in raw:
            return 0.0
        # 解析 v_s_sh600036="1~name~code~price~..."
        body = raw.split('"', 1)[1].rstrip('";').strip('";')
        if not body:
            return 0.0
        parts = body.split("~")
        if len(parts) < 4:
            return 0.0
        price_str = parts[3].strip()
        if not price_str or price_str in ("0", "0.00", "0.0"):
            return 0.0
        return float(price_str)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, Exception):
        return 0.0


# ── Mock 量化数据 (阶段 2 仍占位, 阶段 3 接 dividend_calculator.py) ──────────
def _mock_quant(code: str, name: str, realtime_price: float = 0.0) -> dict:
    """根据股票代码前缀推测市场 + 行业, 给出合理 Mock 数据

    realtime_price 来自腾讯闪电快照, 0.0 表示拉取失败 (停牌/网络/不存在)
    """
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

    return {
        "current_price": realtime_price,  # 真实盘中价, 失败 fallback 0.0
        "estimated_eps": INDUSTRY_BASE_EPS_FALLBACK,  # 动态 EPS 在 handler 中覆盖
        "predicted_dividend_yield": "6.85%",  # 静态 Mock (阶段 3 才接真实计算)
        "industry": industry,
        "qualitative_adjustment": (
            f"实时现价已对接腾讯 qt.gtimg.cn (闪电快照 <50ms); "
            f"EPS 动态年化 (Stage 3 已对接 FinancialDataHub); "
            f"股息率仍 Mock (阶段 4 才接 dividend_calculator.py)"
        ),
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

        # 命中: 拼装响应 (实时现价 → 腾讯 qt.gtimg.cn 闪电快照)
        realtime_price = _fetch_realtime_price(stock["code"])

        # Stage 3: 动态年化 EPS (从 FinancialDataHub 真数据拉)
        eps_info = _fetch_dynamic_eps(stock["code"])

        # 股价 + 动态 EPS 组成 quant; 股价/industry 仍按代码前缀
        quant = _mock_quant(stock["code"], stock["name"], realtime_price)
        quant["estimated_eps"] = eps_info["estimated_eps"]  # 覆盖 Mock
        quant["report_period"] = eps_info["report_period"]  # 新增字段
        quant["eps_source"] = eps_info["source"]            # live / fallback

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
