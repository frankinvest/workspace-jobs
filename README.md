# workspace-jobs — the publishing system behind frankofswing.com

**An Astro + Python pipeline that turns a daily financial briefing into a production website — collected, image-localized, audited, and shipped by Codex CLI every day.**

Live site: **[frankofswing.com](https://frankofswing.com)** · License: **MIT**

> This project uses **Codex CLI as its primary maintainer**. The recurring publishing workflow and most fixes in this repository were authored by Codex, in the open, against production.

## Why this repository exists

Every morning this pipeline takes one financial-briefing article and publishes it as a full website page without manual clicking:

```text
daily briefing source
      │
      ▼
tools/finance_breakfast.py        collect article + nested comments
      │
      ▼
tools/localize_images.py          download signed source images (7-day expiry)
      │                           rewrite them to /images/… site-local paths
      ▼
TLDR generation                   strictly from the article's own frontmatter
      │
      ▼
tools/system_api_pusher.py        commit through the GitHub Contents API
      │
      ▼
tools/audit_local_images.py       verify every image really landed remotely
      │
      ▼
Vercel                            rebuilds frankofswing.com (30–90s)
```

The result is a daily-updating site whose media never rots: source images expire after a week, so every image is stored in this repository and audited against the live site after each push.

## Maintained with Codex CLI — evidence

The commit history is the application's evidence chain:

- **Daily production publishing.** One automated commit per issue, each carrying localized images and rendered comments — see the `feat: 20XX-XX-XX 财经早餐` series ([latest](https://github.com/frankinvest/workspace-jobs/commits/main)).
- **Cron race-condition fix.** The 8AM Saturday job could re-capture the previous day's briefing; fixed and covered in [`95001d7`](https://github.com/frankinvest/workspace-jobs/commit/95001d7).
- **Comment parser rewrite.** Moved fragile inline regex parsing to a BS4-based renderer that handles arbitrarily nested comments ([`acb467e`](https://github.com/frankinvest/workspace-jobs/commit/acb467e), [`707a4ad`](https://github.com/frankinvest/workspace-jobs/commit/707a4ad)).
- **Push tooling for blocked networks.** `tools/system_api_pusher.py` deploys through the GitHub Contents API because direct `git push` is unreachable from the deployment host ([`0744800`](https://github.com/frankinvest/workspace-jobs/commit/0744800)).
- **Frontmatter contract.** Article metadata (title/date/TLDR) became a stable contract consumed by the homepage digest ([`e92dbc7`](https://github.com/frankinvest/workspace-jobs/commit/e92dbc7)).

These are not aspirational use cases — they are fixes and features Codex shipped while keeping a live site healthy.

## What's reusable

If you publish any daily digest (news, research, logs) and want a site instead of a pile of screenshots, the transferable pieces are:

- `tools/finance_breakfast.py` — the orchestrated collect → localize → generate → push flow
- `tools/localize_images.py` — signed-URL image localization so media outlives its source
- `tools/audit_local_images.py` — post-push audit that catches silent GitHub Contents API rate-limit drops (local file exists, remote 404) and repairs them
- `tools/system_api_pusher.py` — Contents-API deploy path for networks where `git push` is blocked

## Quick start

```bash
npm install
npm run dev          # http://localhost:4321
```

Update market data:

```bash
node scripts/wind-market-update.cjs
npm run build
```

Publish one briefing (run from the repository root):

```bash
python3 tools/finance_breakfast.py
```

## Repository layout

```text
src/                 Astro site (components, layouts, pages, utils)
src/pages/           index, docs routes, agents page
public/data/         market_data.json used by the dashboard
public/images/       localized, long-lived article images (JJC-YYYY-MM-DD/)
scripts/             market-data updater
tools/               collecting, localization, audit, and deploy tooling
```

## Operations

- **Cron**: the publishing and market-update jobs run on a local scheduler (`/cron status`, `/cron run market-update`).
- **Data validation**: `public/data/market_data.json` is the dashboard source; `npm run check` and `npm run test` run the site checks.
- **Deploy**: Vercel rebuilds automatically after each Contents-API commit. CDN caches require a cache-busting query when verifying fresh deploys.

## Notes and limitations

1. **Wind data**: the market dashboard currently runs on the checked-in sample dataset; wiring a real Wind API requires configuring its endpoint.
2. **Local images are mandatory**: never hotlink the briefing source images — their signed URLs expire after 7 days. The pipeline enforces localization, and `audit_local_images.py --since <date> --fix` must run after batch pushes.
3. **Deploy path**: this repository intentionally deploys via the GitHub Contents API rather than `git push`.

## Contact

Frank — Telegram [@lick789] · Timezone: Asia/Shanghai (GMT+8)

## License

[MIT](./LICENSE) — collect, localize, audit, and publish your own daily digest with it.
