// Vercel serverless function: /api/dash —— 控制台密文的**即时**读取端点（2026-10-09，方案 A）
//
// 为什么需要它（都是实测结论，别再试别的路）：
//   1) raw.githubusercontent.com 自带 300 秒 Fastly 缓存，查询串和 Cache-Control 请求头都绕不过；
//   2) Vercel 的 rewrite 代理还会在它上面再叠一层 300 秒 → 手机上最坏 10 分钟；
//   3) 但 raw.githubusercontent.com/<repo>/<commit-sha>/<path> 是**从未出现过的 URL**（首抓必 MISS）→ 即时；
//      拿最新 SHA 用 github.com 的 commit atom feed（不走 API 速率限制，也不需要任何账号）。
// 若在 Vercel 项目里配了 GH_TOKEN 环境变量，则优先走 GitHub API（更稳更快，5000 次/小时）。
//
// 降级顺序：API(token) → atom(SHA)+raw(by sha) → raw(by branch, 最多 300s 陈旧) → 页面再降级到本地/CDN
//
// 用法: GET /api/dash   （忽略查询串；总是 Cache-Control: no-store）

const REPO = "frankinvest/agent-dashboard-preview";
const PATH = "data/agent-dashboard.enc.json";
const BRANCH = "main";
const RAW_BY_REF = (ref) => `https://raw.githubusercontent.com/${REPO}/${ref}/${PATH}`;
const ATOM = `https://github.com/${REPO}/commits/${BRANCH}.atom`;
const API_URL = `https://api.github.com/repos/${REPO}/contents/${PATH}?ref=${BRANCH}`;

const SHA_TTL_MS = 15000; // SHA 缓存 15s：省 github.com 抓取，同时保证 ≤15s 的新鲜度
let shaCache = null;

function isBlob(txt) {
  try {
    const d = JSON.parse(txt);
    return !!d && typeof d.ct === "string" && d.ct.length > 32;
  } catch {
    return false;
  }
}

async function latestSha() {
  if (shaCache && Date.now() - shaCache.at < SHA_TTL_MS) return shaCache.sha;
  try {
    const r = await fetch(ATOM, {
      headers: { "user-agent": "frankofswing-dash/1.0" },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!r.ok) return null;
    const m = (await r.text()).match(/Grit::Commit\/([0-9a-f]{40})/);
    if (!m) return null;
    shaCache = { sha: m[1], at: Date.now() };
    return m[1];
  } catch {
    return null;
  }
}

export default async function handler(req, res) {
  const tok = process.env.GH_TOKEN || process.env.GITHUB_TOKEN;
  const send = (txt, via) => {
    res.setHeader("content-type", "application/json; charset=utf-8");
    // 关键：不让 Vercel / 浏览器再缓存一层（否则又变回 5-10 分钟）
    res.setHeader("cache-control", "no-store, max-age=0, must-revalidate");
    res.setHeader("x-dash-via", via);
    res.status(200).send(txt);
  };

  try {
    // 1) token → GitHub API（无 CDN 缓存）
    if (tok) {
      try {
        const r = await fetch(API_URL, {
          headers: {
            authorization: `Bearer ${tok}`,
            accept: "application/vnd.github.raw+json",
            "user-agent": "frankofswing-dash/1.0",
          },
          cache: "no-store",
          signal: AbortSignal.timeout(6000),
        });
        if (r.ok) {
          const txt = await r.text();
          if (isBlob(txt)) return send(txt, "api-token");
        }
      } catch (_) {
        /* 落下一档 */
      }
    }

    // 2) 无 token：atom 取最新 SHA → 按 SHA 取 raw（新 URL，不命中 CDN 缓存）
    const sha = await latestSha();
    if (sha) {
      try {
        const r = await fetch(RAW_BY_REF(sha), { cache: "no-store", signal: AbortSignal.timeout(6000) });
        if (r.ok) {
          const txt = await r.text();
          if (isBlob(txt)) return send(txt, "raw-by-sha");
        }
      } catch (_) {
        /* 落下一档 */
      }
    }

    // 3) 兜底：按分支取 raw（最多 300s 陈旧，总比没有强）
    try {
      const r = await fetch(`${RAW_BY_REF(BRANCH)}?t=${Date.now()}`, {
        cache: "no-store",
        signal: AbortSignal.timeout(6000),
      });
      if (r.ok) {
        const txt = await r.text();
        if (isBlob(txt)) return send(txt, "raw-branch-fallback");
      }
    } catch (_) {
      /* ignore */
    }

    res.setHeader("cache-control", "no-store");
    res.status(502).json({ error: "dash upstream unavailable" });
  } catch (err) {
    console.error("[api/dash] unhandled:", err);
    try {
      res.setHeader("cache-control", "no-store");
      res.status(500).json({ error: err && err.message ? err.message : String(err) });
    } catch (_) {
      /* headers already sent */
    }
  }
}
