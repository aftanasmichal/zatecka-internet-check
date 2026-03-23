# Žatecká Internet Check

Dashboard monitoring internet stability at the PFC office on Žatecká street, Prague.
Tracks two SD-WAN links reported by the FortiGate FGT-40 router via email.

**Live dashboard:** https://zatecka-internet-check.pages.dev
**GitHub repo:** https://github.com/aftanasmichal/zatecka-internet-check

---

## Connections monitored

| Interface | Provider | Speed | Type | Cost | Role |
|-----------|----------|-------|------|------|------|
| `wan` | Internet Praha Josefov | 250/250 Mbps | Optical | 4 928 CZK/mo | Primary |
| `a` | O2 5G | 100/20 Mbps | 5G | 599 CZK/mo | Backup |

---

## How it works

```
FortiGate router (FGT-40)
  → sends email to fgt@palefire.com on every link up/down event
  → received at michal@palefire.com (label: FortiGate)

GitHub Actions (every 5 min, runs on GitHub servers — no laptop needed)
  → scripts/poll.py fetches emails via Gmail API
  → new events appended to data/events-001.json (deduplicated by eventtime)
  → if new data: git commit + push + Cloudflare Pages redeploy

Dashboard (https://zatecka-internet-check.pages.dev)
  → static HTML/JS, reads data/*.json from same domain
  → shows current status, uptime %, 7-day timeline, incidents
  → "Check Now" button triggers immediate poll via Cloudflare Worker proxy
  → "Last checked" timestamp pulled from GitHub Actions API
```

---

## File structure

```
.github/workflows/poll.yml   GitHub Actions cron job (every 5 min)
data/index.json              Lists all data files
data/events-001.json         Event log (rotates at 10 MB → events-002.json, etc.)
index.html                   Dashboard (single static file)
scripts/poll.py              Polls Gmail API, ingests new events
scripts/ingest.py            Core: parses FortiGate HTML email → event dict, appends to JSON
worker/index.js              Cloudflare Worker: proxy for "Check Now" button
worker/wrangler.toml         Worker deployment config
```

---

## Secrets & credentials

| Secret | Stored in | Used by |
|--------|-----------|---------|
| `GMAIL_CLIENT_ID` | GitHub Actions Secret | poll.py — Gmail API auth |
| `GMAIL_CLIENT_SECRET` | GitHub Actions Secret | poll.py — Gmail API auth |
| `GMAIL_REFRESH_TOKEN` | GitHub Actions Secret | poll.py — Gmail API auth |
| `CLOUDFLARE_API_TOKEN` | GitHub Actions Secret | wrangler pages deploy |
| `GITHUB_TOKEN` (gh CLI OAuth) | Cloudflare Worker Secret | "Check Now" → trigger workflow dispatch |

Local credential files (bootstrap only, not used by automation):
- `C:\Users\afink\.gmail-mcp\palefire\gcp-oauth.keys.json` — client_id + client_secret
- `C:\Users\afink\.gmail-mcp\palefire\credentials.json` — refresh_token

Gmail OAuth app: Google Cloud project `claude-gmail-490805`

---

## Data format

Each event in `data/events-*.json`:
```json
{
  "ts":    "2026-03-23T04:47:38+01:00",
  "iface": "a",
  "from":  "dead",
  "to":    "alive",
  "eid":   "1774237658842957320"
}
```

- `eid` = FortiGate `eventtime` nanosecond timestamp — used for deduplication
- `iface`: `wan` (main optical) or `a` (O2 5G backup)
- `from`/`to`: `alive` or `dead`

File rotation: when `events-001.json` hits 10 MB, a new `events-002.json` is created.
`data/index.json` always lists all files; dashboard loads all of them.

---

## Deployment

### Cloudflare Pages (dashboard)
```bash
cd projects/work/zatecka-internet-check
wrangler pages deploy . --project-name zatecka-internet-check --branch main --commit-dirty=true
```

### Cloudflare Worker ("Check Now" proxy)
```bash
cd projects/work/zatecka-internet-check/worker
wrangler deploy
```

### GitHub Actions secrets (if re-setting up)
```bash
gh secret set GMAIL_CLIENT_ID -R aftanasmichal/zatecka-internet-check
gh secret set GMAIL_CLIENT_SECRET -R aftanasmichal/zatecka-internet-check
gh secret set GMAIL_REFRESH_TOKEN -R aftanasmichal/zatecka-internet-check
gh secret set CLOUDFLARE_API_TOKEN -R aftanasmichal/zatecka-internet-check
# GITHUB_TOKEN is set as a Cloudflare Worker secret, not GitHub:
gh auth token | wrangler secret put GITHUB_TOKEN --name zatecka-check-now
```

---

## Costs

Everything is free:
- **GitHub Actions** — unlimited minutes (public repo)
- **Cloudflare Pages** — unlimited requests and deploys
- **Cloudflare Worker** — 100 000 req/day free (Check Now button only)
- **Gmail API** — free well within quota

---

## Maintenance notes

- **Gmail refresh token expires?** Unlikely (Google only expires tokens after 6 months of inactivity or if OAuth app consent is revoked). If it does: re-run `gmail-mcp` auth for palefire account, update `GMAIL_REFRESH_TOKEN` GitHub Secret.
- **GitHub OAuth token (for Worker) expires?** Run `gh auth token | wrangler secret put GITHUB_TOKEN --name zatecka-check-now` from the project's `worker/` directory.
- **Adding a new interface?** Add it to the `IFACES` object in `index.html`. FortiGate emails will be picked up automatically as long as the interface name in the email matches.
- **Data file rotation?** Handled automatically by `scripts/poll.py`. Old files stay read-only in the repo forever; `data/index.json` lists all of them and the dashboard loads all.
