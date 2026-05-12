# AI Industry Intelligence Engine — v1 Spec

**Status:** locked, pre-build
**Owner:** Kay
**Last updated:** 2026-05-12

## Mission

Discover hidden champions and future champions in the AI infrastructure stack and adjacencies — names Kay does not yet know — and surface them with explainable evidence on a cadence that matches the actual rate at which such names emerge. The engine never recommends trades; it surfaces candidates and a one-line "why."

## Operator profile

- Swiss-resident private investor; **safe-harbor preservation under Kreisschreiben Nr. 36 is the prime directive**.
- Capital: USD 2–3M risk capital earmarked. Sizing: $50–100k per name, $200–300k per theme, 4–6 active themes.
- Horizon: months to years. Discovery thesis runs 6–24 months. No swing trading.
- Broker: Julius Baer @ 10bps. Self-execute via e-banking OR RM handoff per candidate.
- Geography: ADRs + EU + selective Asia direct (RM-flagged).

## Primary KPI

**≥ 3 genuinely new names per month** surfaced and accepted as plausible AI-infra exposure, where "new" means not on the operator's exclusion list. Reframed from "predict next bottleneck" to **earlier participation in rotations** — surface a thematic shift within 60 days of it showing up in transcripts/capex/holdings, before broad analyst recognition.

## Safe-harbor constraints (hard, non-negotiable)

- Min 6-month holding period for all positions (recurring pattern, not just per-trade).
- Annual transaction turnover ≤ portfolio value.
- Capital gains ≤ 50% of net income from other sources.
- No debt-financed positions.
- Derivatives only as hedge on existing holdings or as asymmetric exposure to an existing thesis — never as primary alpha source.

System must enforce these via the safe-harbor monitor before any candidate ranks above "watch."

## Architecture — five layers

```
DISCOVERY LAYER     ← the product
 ├─ Thematic Discovery (research corpus + transcripts buzzword deltas)
 └─ Hidden Champion Finder (ETF diffs, 13Fs, supply chain mapping)
       │ proposes new universe additions
       ▼
DATA LAYER
 ├─ Universe DB (Postgres on Neon + Notion mirror)
 ├─ Fundamentals + filings + news cache
 ├─ Smart-money cache (13Fs, ETF holdings, hedge-fund letters)
 └─ Research corpus (PDFs + extracted highlights)
       │ feeds
       ▼
SIGNAL LAYER (triage, not screening)
 ├─ Rule-based scoring (valuation, revisions, beats, sentiment, insider)
 ├─ Safe-harbor monitor (turnover, hold-period, derivative usage)
 └─ Recommendation packager (sizing, R/R, execution path)
       │ scored candidates
       ▼
OUTPUT LAYER
 ├─ Monthly Discovery Report composer (LLM, deterministic input)
 ├─ Rapid Alert engine (threshold-triggered, soft-cap ~2/wk)
 ├─ Email sender (Resend)
 ├─ Notion sync (universe + watchlist always current)
 └─ RM-handoff brief generator (one-page PDF)

ORCHESTRATION: Modal scheduled functions
SECRETS: Modal Secrets   CODE: GitHub
```

## Output cadence

| Channel | Cadence | Content | Trigger |
|---|---|---|---|
| Monthly Discovery Report | 1st Monday, 07:00 CET | 3–8 new candidates, thematic rotation, smart-money flow, watchlist health | Scheduled |
| Rapid Alert (email) | As-it-happens, ≤2/wk | Material event on watchlist/candidate (big 13F add, unusual options, insider buy > threshold, beat+guide-raise combo) | Threshold |
| Notion sync | Continuous | Universe + watchlist state | Daily |

No weekly digest. Weekly slot is Notion-only refresh.

## Job schedule (UTC)

| Job | Cadence | Time |
|---|---|---|
| Price + fundamentals ingest | Daily | 04:00 |
| Filings + 13F ingest | Daily | 06:00 |
| ETF holdings diff | Daily | 21:30 (post-close) |
| Transcript pull | Daily | 22:00 |
| Sentiment scoring | Daily | 03:00 |
| Thematic discovery sweep | Weekly Sun | 18:00 |
| Hidden-champion sweep | Weekly Sun | 19:00 |
| Rapid-alert evaluator | Hourly during market hours | — |
| Monthly Discovery Report compose | 1st Sun of month | 22:00 |
| Monthly report send | 1st Mon of month | 06:00 (07:00 CET) |

## Tech stack

| Component | Choice |
|---|---|
| Language | Python 3.12 |
| Package manager | `uv` |
| Runtime | Modal (cron, secrets, scheduled functions) |
| Database | Neon Postgres (serverless, free tier OK for v1) |
| ORM | SQLModel |
| LLM | Anthropic SDK direct, prompt caching enabled. Haiku for high-volume scoring, Sonnet for synthesis, Opus for monthly report narrative. |
| Email | Resend (free 100/day) |
| Templating | Jinja2 |
| Notion sync | `notion-client` |
| Source control | GitHub private repo |
| CI/CD | GitHub Actions → Modal deploy on push to main |

## Data sources & budget

| Layer | Source | Cost |
|---|---|---|
| Fundamentals (global) | Financial Modeling Prep Premium | $50/mo |
| Filings (US) | SEC EDGAR + `sec-api` | $0 |
| Filings (EU/Asia) | Direct scrape per exchange on universe names | $0 |
| Transcripts | Aiera (via `financial-analysis` plugin MCP) | $200/mo |
| News | Marketaux + free RSS | $30/mo |
| Smart-money / 13Fs | WhaleWisdom Premium | $60/mo |
| ETF holdings diff | Issuer page scrapers (iShares, ARK, Global X, Roundhill, etc.) | $0 |
| Hedge-fund letters | Quarterly scrape + LLM extract | $0 |
| Research reports | Drop-folder + Claude PDF extraction | $0 + LLM |
| Sentiment | Haiku scoring | included in LLM |
| Storage | Neon Postgres free tier | $0 |
| Orchestration | Modal | ~$30/mo |
| Email | Resend free tier | $0 |
| LLM compute | Claude API | ~$50/mo |
| **Total** | | **~$420/mo** |

## Phased build

### Weeks 1–2 — v0: foundation + manual first report

- Modal + Neon + GitHub + Resend provisioned
- Universe DB schema in Postgres + Notion mirror
- Seed ~30 names across compute / memory / networking / optics / power / packaging
- Daily ingest: FMP fundamentals + SEC filings + Yahoo prices
- WhaleWisdom 13F alerts wired
- ETF holdings diff for 6 AI/semis ETFs
- Manual Discovery Report #1 composed from cache, sent by hand to validate format
- **Gate:** ingest reliable 7 days running; universe queryable; first manual report accepted

### Weeks 3–4 — v1: signal layer + automated monthly + rapid alerts

- Signal scoring rules as triage on discovery output
- Resend HTML monthly template; cron live (1st Mon 07:00 CET)
- Rapid Alert engine: threshold rules + soft-cap dedupe
- Mark-as-known feedback loop (Notion checkbox → exclusion list)
- Sentiment via Haiku on news + transcripts
- Safe-harbor turnover monitor (portfolio-level, not per-trade)
- **Gate:** first automated monthly delivered; rapid-alert false-positive rate < 20%; mark-as-known working

### Weeks 5–6 — v1.5: thematic discovery + RM brief

- Research-report drop folder + Claude PDF extraction
- Hedge-fund letter quarterly scrape + extract
- Thematic Discovery: buzzword-frequency deltas across transcripts + research corpus
- Options layer for top-conviction names (IV/skew/term structure)
- RM-handoff brief generator (one-page PDF, thesis + sizing + limit price)
- **Gate:** ≥3 genuinely new names surfaced over prior 4 weeks; thematic ranking shows movement; zero safe-harbor false positives

## Top 5 risks

1. **Discovery returns noise.** Mitigation: track precision (% surfaced names accepted), not volume. If <30% by week 4, tighten criteria.
2. **Cost creep.** Mitigation: monthly cost line item in the report itself. Kill any source whose contribution isn't visible in surfaced candidates.
3. **Signal overfitting.** Mitigation: paper-trade signals 3 months before sizing real $. Engine surfaces candidates, never recommends trades.
4. **Safe-harbor false positives.** Mitigation: portfolio-level turnover monitor; soft-block any Q4 recommendation if YTD turnover approaching 90% of portfolio.
5. **Asia data quality.** Mitigation: Asia-direct names flagged as "RM execution + manual DD verify."

## Non-goals for v1

- Backtesting framework. The engine surfaces; doesn't optimize itself.
- ML models. Transparent rules only.
- Buy/sell recommendations. Candidates with evidence; operator decides.
- Universe of 500+. Quality over coverage. Universe grows via discovery.
- Real-time trading integration. Output is read, not executed.
