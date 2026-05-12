# Setup Checklist — External Services

**Chosen path: defer paid subs to week 2.** Week 1 uses free tier only.

You (Kay) need to create the 4 accounts below. Each line tells you exactly what to do and what to paste back. Order matters — earlier items are dependencies for later ones.

## Week 1 — free tier only (~$0/mo)

### 1. GitHub repo (free)

- Create a new private repo `signal-engine` under your GitHub account.
- Do NOT initialize it with README/license — I'll push the local files.
- Paste back: repo URL (SSH format, e.g. `git@github.com:kaykuehne/signal-engine.git`).

### 2. Neon Postgres (free tier)

- Sign up at https://console.neon.tech with Google.
- Create a project named `signal-engine`.
- Region: **AWS Frankfurt (`eu-central-1`)** — closest to Switzerland and to Modal's EU region.
- Copy the **pooled** connection string from the dashboard (the one that contains `-pooler` in the host).
- Paste back: the full connection string.

### 3. Modal (free tier)

- Sign up at https://modal.com with GitHub.
- After signup, you'll be told to install the CLI. Don't run anything yet — I'll set up the local CLI with you together.
- Paste back: "Modal signed up, GitHub workspace = `<workspace name>`".

### 4. Resend (free tier — 100 emails/day)

- Sign up at https://resend.com with Google.
- Generate an API key from the dashboard.
- For v0, we'll send from `onboarding@resend.dev` (no domain verification needed). Switch to a verified domain in week 3.
- Paste back: the API key (I'll move it to Modal Secrets immediately).

### Anthropic API (you already have)

- I'll reuse your existing `ANTHROPIC_API_KEY`. Paste it back here so I can wire it into Modal Secrets.

## Week 2 — paid subs (~$420/mo, added when v0 plumbing works)

| Service | $/mo | When |
|---|---|---|
| Financial Modeling Prep Premium | $50 | Week 2 day 1 |
| WhaleWisdom Premium | $60 | Week 2 day 1 |
| Marketaux Standard | $30 | Week 2 day 3 |
| Aiera transcripts (via plugin) | $200 | Week 2 day 5 |

You'll sign up for these only after v0 has run a successful daily ingest for 7 consecutive days on free data sources (Yahoo Finance + SEC EDGAR). That's the gate.

## What I do once you paste back accounts 1–4 + your Anthropic key

1. Initialize git repo locally, set remote, first push.
2. Install Modal CLI, authenticate, create `signal-engine` workspace.
3. Create Modal Secrets bundle with all keys.
4. Run `scripts/init_db.py` against Neon → schema applied.
5. Run `scripts/seed_universe.py` → 30 names loaded, all marked `is_excluded=TRUE`.
6. Verify in Neon dashboard: 30 rows in `companies`, 20 in `themes`, ~40 in `company_themes`.

After that, week 1 work continues: write the ingest jobs (Yahoo prices, SEC filings, ETF holdings scrapers) and schedule them on Modal.

## Paste-back template

```
1. GitHub: <repo URL>
2. Neon: <pooled connection string>
3. Modal: signed up, workspace = <name>
4. Resend: <api key>
5. Anthropic: <existing api key>
```
