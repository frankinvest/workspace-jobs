// /api/dash —— 控制台数据的**即时**读取端点（2026-10-09，Frank 选方案 A）
//
// 为什么需要它（实测结论，别再试别的路）：
//   · raw.githubusercontent.com 自带 300 秒 Fastly 缓存，**查询串和 Cache-Control 请求头都绕不过**；
//   · Vercel 的 rewrite 代理还会在它上面再叠一层 300 秒 → 手机上最坏 10 分钟。
//   · 而 `raw.githubusercontent.com/<repo>/<commit-sha>/<path>` 是**从未出现过的 URL**（首次抓取必 MISS）
//     → 即时。配合 github.com 的 commit atom feed（不走 API 速率限制）拿最新 SHA，就得到一条
//     零账号、零部署额度的即时通道。
// 若配了 GH_TOKEN 环境变量，则优先走 GitHub API（更稳、更快，5000 次/小时）。
//
// 降级顺序：API(token) → atom(SHA)+raw(by sha) → raw(by branch, 最多 300s 陈旧) → 交给页面再降级到 CDN
export const prerender = false;

const REPO = "frankinvest/agent-dashboard-preview";
const PATH = "data/agent-dashboard.enc.json";
const BRANCH = "main";
const RAW_BY_REF = (ref: string) => `https://raw.githubusercontent.com/${REPO}/${ref}/${PATH}`;
const ATOM = `https://github.com/${REPO}/commits/${BRANCH}.atom`;
const API_URL = `https://api.github.com/repos/${REPO}/contents/${PATH}?ref=${BRANCH}`;

const SHA_TTL_MS = 15000;               // SHA 缓存 15s：既省 github.com 的抓取，又保证 ≤15s 的新鲜度
let shaCache: { sha: string; at: number } | null = null;

function ok(body: string, via: string): Response {
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": "application/json; charset=utf-8",
      // 关键：不让 Vercel/浏览器再缓存一层（否则又变回 5-10 分钟）
      "cache-control": "no-store, max-age=0, must-revalidate",
      "x-dash-via": via,
      "access-control-allow-origin": "*",
    },
  });
}

function isBlob(txt: string): boolean {
  try {
    const d = JSON.parse(txt);
    return !!d && typeof d.ct === "string" && d.ct.length > 32;
  } catch {
    return false;
  }
}

async function latestSha(): Promise<string | null> {
  if (shaCache && Date.now() - shaCache.at < SHA_TTL_MS) return shaCache.sha;
  try {
    const r = await fetch(ATOM, {
      headers: { "user-agent": "frankofswing-dash/1.0" },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!r.ok) return null;
    const txt = await r.text();
    const m = txt.match(/Grit::Commit\/([0-9a-f]{40})/);
    if (!m) return null;
    shaCache = { sha: m[1], at: Date.now() };
    return m[1];
  } catch {
    return null;
  }
}

export async function GET(): Promise<Response> {
  const tok = process.env.GH_TOKEN || process.env.GITHUB_TOKEN;

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
        if (isBlob(txt)) return ok(txt, "api-token");
      }
    } catch {
      /* 落到下一档 */
    }
  }

  // 2) 无 token：atom 取最新 SHA → 按 SHA 取 raw（新 URL，不命中 CDN 缓存）
  const sha = await latestSha();
  if (sha) {
    try {
      const r = await fetch(RAW_BY_REF(sha), { cache: "no-store", signal: AbortSignal.timeout(6000) });
      if (r.ok) {
        const txt = await r.text();
        if (isBlob(txt)) return ok(txt, "raw-by-sha");
      }
    } catch {
      /* 落到下一档 */
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
      if (isBlob(txt)) return ok(txt, "raw-branch-fallback");
    }
  } catch {
    /* ignore */
  }

  return new Response(JSON.stringify({ error: "dash upstream unavailable" }), {
    status: 502,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}
