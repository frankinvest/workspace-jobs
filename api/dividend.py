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
import time
from pathlib import Path

import requests

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


# ── 方案B: Upstash Redis 云端 KV 双轨 (2026-06-10) ──────────────────────────
# Vercel KV 已在 2024-11 迁移到 Marketplace 上的 Upstash for Redis 集成
# 环境变量名: UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN
# (Frank v3 提示的 KV_REST_API_URL/TOKEN 是旧名, 已弃用)
KV_REST_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
KV_REST_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
KV_AVAILABLE = bool(KV_REST_URL and KV_REST_TOKEN)

# ── 方案B: 内存沙盒 fallback (2026-06-10) ──────────────────────────────────
# Upstash 未装时, 用模块级 dict 作为临时价帊
# Vercel serverless 冷启动后会重置 (预览环境) / 预热后保持 (production)
# Frank 预览场景足够演示 UI 交互, 真 KV 装好后会自动切上
_PRICE_CACHE: dict = {}


def _kv_get_price(code: str):
    """Upstash Redis REST: GET {url}/get/stock_price:{code}
    返回 (price, source) 或 (None, None) 表示未命中/不可用
    """
    if not KV_AVAILABLE:
        return None, None
    try:
        r = requests.get(
            f"{KV_REST_URL}/get/stock_price:{code}",
            headers={"Authorization": f"Bearer {KV_REST_TOKEN}"},
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            result = data.get("result")
            if result is not None and str(result).strip():
                return float(result), "upstash_kv"
        return None, None
    except Exception as e:
        print(f"[dividend][kv] GET 异常 {code}: {type(e).__name__}: {str(e)[:100]}", file=sys.stderr)
        return None, None


def _kv_set_price(code: str, price: float, ttl_seconds: int = 86400) -> bool:
    """Upstash Redis REST: POST {url}/set/stock_price:{code}/{price}?ex={ttl}
    24h TTL 足够盘中周期重刷
    """
    if not KV_AVAILABLE:
        return False
    try:
        r = requests.post(
            f"{KV_REST_URL}/set/stock_price:{code}/{price}",
            headers={"Authorization": f"Bearer {KV_REST_TOKEN}"},
            params={"ex": str(ttl_seconds)},
            timeout=5,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[dividend][kv] SET 异常 {code}: {type(e).__name__}: {str(e)[:100]}", file=sys.stderr)
        return False


def _memory_set_price(code: str, price: float) -> None:
    """内存沙盒写入 (Upstash 未装时的 fallback)"""
    _PRICE_CACHE[code] = price


def _fetch_real_price_via_hub(code: str):
    """FinancialDataHub.fetch_fast_snapshot 闪电拦截真现价 (hq.sinajs.cn 0.06s)
    返回 float 或 None
    """
    if _HUB_INSTANCE is None:
        return None
    # 补全 sina hq 需要的 sh/sz/bj 前缀
    if code.startswith("6") or code.startswith("5"):
        market = "sh"
    elif code.startswith(("0", "3")):
        market = "sz"
    elif code.startswith(("8", "4", "9")):
        market = "bj"
    else:
        market = "sh"
    # fetch_fast_snapshot 返回的 key 形如 "sh600036" (带 sh/sz/bj 前缀)
    market_code = f"{market}{code}"
    snap = _HUB_INSTANCE.fetch_fast_snapshot([market_code])
    if isinstance(snap, dict) and market_code in snap:
        return snap[market_code].get("price")
    return None


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


# ── 实时现价拉取 (从 stock_index.json 静态字典直读) ──────────────────────────
# 1. 由于 stock_index.json 本身已经过 generate_stock_index.py 离线落库了最新价格
#    api 运行时不再发外部请求, 避免腾讯接口限速 / Vercel 运行时网络依赖。
# 2. 静态字典里的价格是收盘后到下一次跑 generate 之间的"上一个批次价格",
#    对首页面板足够使用 (非高频实时监控场景)。


def _fetch_realtime_price(code: str) -> float:
    """从 STOCK_BY_CODE 静态字典直读价格, 任何异常 fallback 0.0

    数据源: public/data/stock_index.json (由 tools/generate_stock_index.py 生成)
    """
    try:
        s = STOCK_BY_CODE.get(code)
        if not s:
            return 0.0
        price = float(s.get("price", 0.0))
        return round(price, 2) if price > 0 else 0.0
    except (TypeError, ValueError, Exception):
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
            f"现价 + 行业 均从 public/data/stock_index.json 静态字典直读 (v2 升级); "
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
        action = (qs.get("action") or [""])[0].lower()

        if not query:
            self._respond_json(400, _error_response(
                400, "MISSING_PARAM",
                "缺少必填参数: code (股票代码或简称)",
            ))
            return

        # 方案B 路由分流: action=update 走重刷; 其余走查询
        if action == "update":
            self._handle_update_price(query)
        else:
            self._handle_query_price(query)

    def _handle_query_price(self, query: str):
        """查询: 基础名/行业从 stock_index.json, 价若从 Upstash KV/内存沙盒, EPS 从 FinancialDataHub"""
        stock, match_type = _lookup(query)
        if stock is None:
            self._respond_json(404, _error_response(
                404, "NOT_FOUND",
                f"未在 stock_index.json 找到匹配项 (库内 {len(STOCK_INDEX)} 只股票)",
                query=query,
            ))
            return

        # 双轨价格: Upstash KV → 内存沙盒 → 静态 JSON
        kv_price, kv_src = _kv_get_price(stock["code"])
        static_price = _fetch_realtime_price(stock["code"])
        if kv_price is not None and kv_price > 0:
            realtime_price, price_source = kv_price, kv_src
        elif stock["code"] in _PRICE_CACHE and _PRICE_CACHE[stock["code"]] > 0:
            realtime_price, price_source = _PRICE_CACHE[stock["code"]], "memory_sandbox"
        else:
            realtime_price, price_source = static_price, "static_json"

        # Stage 3: 动态年化 EPS
        eps_info = _fetch_dynamic_eps(stock["code"])

        quant = _mock_quant(stock["code"], stock["name"], realtime_price)
        quant["estimated_eps"] = eps_info["estimated_eps"]
        quant["report_period"] = eps_info["report_period"]
        quant["eps_source"] = eps_info["source"]
        quant["price_source"] = price_source  # 方案B 新增: 价帊来源 (upstash_kv/memory_sandbox/static_json)

        # 行业从 stock_index.json 读取
        real_industry = stock.get("industry", quant.get("industry", "未分类"))
        if real_industry and real_industry != "未分类":
            quant["industry"] = real_industry

        # 方案B: 价若从 KV 来, 标个动态股息率重算 hint
        if price_source == "upstash_kv":
            quant["qualitative_adjustment"] = (
                f"现价 从 Upstash Redis 云端动态取 (上一次交易重刷保留); "
                f"EPS 动态年化 (FinancialDataHub 拉取); "
                f"点击【更新现价】按钮可实时重刷"
            )
        elif price_source == "memory_sandbox":
            quant["qualitative_adjustment"] = (
                f"现价 从运行时内存沙盒取 (Upstash 未装时降级); "
                f"冷启动后丢失, 建议在 Vercel Dashboard 装 Upstash for Redis 集成以启用云端持久"
            )

        result = {
            "code": stock["code"],
            "name": stock["name"],
            "match_type": match_type,
            **quant,
        }
        self._respond_json(200, result)

    def _handle_update_price(self, query: str):
        """方案B: 更新现价 - 闪电拦截真价 → 写 Upstash KV/内存沙盒 → 回传"""
        stock, match_type = _lookup(query)
        if stock is None:
            self._respond_json(404, _error_response(
                404, "NOT_FOUND",
                f"未在 stock_index.json 找到匹配项 (库内 {len(STOCK_INDEX)} 只股票)",
                query=query,
            ))
            return

        code = stock["code"]
        # old_price 优先从内存沙盒/KV 取 (体现上一次重刷结果), fallback 静态 JSON
        kv_old, _ = _kv_get_price(code)
        if kv_old is not None and kv_old > 0:
            old_price = kv_old
        elif code in _PRICE_CACHE and _PRICE_CACHE[code] > 0:
            old_price = _PRICE_CACHE[code]
        else:
            old_price = _fetch_realtime_price(code)

        # 1. 闪电拦截真现价 (FinancialDataHub.fetch_fast_snapshot 走 hq.sinajs.cn)
        new_price = _fetch_real_price_via_hub(code)
        if new_price is None or new_price <= 0:
            # Hub 不可用或拦截失败, 保持原状但记录错误
            self._respond_json(503, {
                "error": f"闪电拦截真价失败 (code={code}), Hub 不可用或网络异常",
                "code": "HUB_UNAVAILABLE",
                "query": query,
                "old_price": old_price,
            })
            return

        # 2. 双轨写入: 优先 Upstash KV, 失败回退内存沙盒
        kv_ok = _kv_set_price(code, new_price, ttl_seconds=86400)
        _memory_set_price(code, new_price)  # 同步写入内存 (保证 fallback 一致性)

        # 3. 重组响应
        result = {
            "code": code,
            "name": stock["name"],
            "match_type": match_type,
            "old_price": round(old_price, 2) if old_price else None,
            "new_price": round(new_price, 2),
            "price_source": "upstash_kv" if kv_ok else "memory_sandbox",
            "kv_written": kv_ok,
            "industry": stock.get("industry", "未分类"),
            "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "message": "真价闪电拦截 + 云端持久成功" if kv_ok else "真价闪电拦截成功, 云端写入失败, 回退内存沙盒 (建议装 Upstash 集成)",
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
