-- AI Signal Engine — Postgres schema (Neon)
-- See SPEC.md for the architecture this supports.

-- Theme taxonomy. Edited by hand, not by jobs.
CREATE TABLE IF NOT EXISTS themes (
    id              SERIAL PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    bottleneck_layer TEXT,
    parent_slug     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Universe: companies the engine tracks.
CREATE TABLE IF NOT EXISTS companies (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    name            TEXT NOT NULL,
    country         TEXT,
    currency        TEXT,
    market_cap_usd  NUMERIC(20, 2),
    adv_usd         NUMERIC(20, 2),         -- avg daily volume, USD
    is_excluded     BOOLEAN NOT NULL DEFAULT FALSE,  -- mark-as-known
    excluded_at     TIMESTAMPTZ,
    excluded_reason TEXT,
    notes           TEXT,
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    discovered_via  TEXT,                   -- e.g. 'seed', 'etf_diff:SOXX', 'thirteen_f:Coatue'
    last_seen_at    TIMESTAMPTZ,
    UNIQUE (ticker, exchange)
);
CREATE INDEX IF NOT EXISTS idx_companies_excluded ON companies (is_excluded);
CREATE INDEX IF NOT EXISTS idx_companies_discovered_at ON companies (discovered_at DESC);

-- Many-to-many: a company can map to multiple themes.
CREATE TABLE IF NOT EXISTS company_themes (
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    theme_id        INT NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
    weight          REAL NOT NULL DEFAULT 1.0,  -- 1.0 = primary exposure, 0.3 = adjacent
    PRIMARY KEY (company_id, theme_id)
);

-- ============================================================
-- Data layer: ingested artifacts
-- ============================================================

-- Daily price + return snapshot.
CREATE TABLE IF NOT EXISTS prices_daily (
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    close_local     NUMERIC(18, 6),
    close_usd       NUMERIC(18, 6),
    volume          BIGINT,
    PRIMARY KEY (company_id, date)
);

-- Fundamentals snapshot (point-in-time).
CREATE TABLE IF NOT EXISTS fundamentals (
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    as_of           DATE NOT NULL,
    pe_ttm          REAL,
    pe_forward      REAL,
    ev_ebitda       REAL,
    ev_sales        REAL,
    revenue_ttm_usd NUMERIC(20, 2),
    eps_ttm         REAL,
    revenue_growth_yoy REAL,
    gross_margin    REAL,
    operating_margin REAL,
    source          TEXT NOT NULL,           -- 'fmp', 'yfinance', etc.
    PRIMARY KEY (company_id, as_of, source)
);

-- Earnings event: each quarterly print.
CREATE TABLE IF NOT EXISTS earnings_events (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    fiscal_period   TEXT NOT NULL,           -- e.g. 'Q1 2026'
    reported_at     TIMESTAMPTZ NOT NULL,
    eps_actual      REAL,
    eps_estimate    REAL,
    eps_surprise_pct REAL,
    revenue_actual_usd NUMERIC(20, 2),
    revenue_estimate_usd NUMERIC(20, 2),
    revenue_surprise_pct REAL,
    guidance_direction TEXT,                  -- 'up', 'down', 'in_line', 'none'
    UNIQUE (company_id, fiscal_period)
);

-- Analyst price targets and revisions.
CREATE TABLE IF NOT EXISTS analyst_targets (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    analyst         TEXT,
    firm            TEXT,
    target_price    NUMERIC(18, 4),
    target_currency TEXT,
    rating          TEXT,                     -- 'buy', 'hold', 'sell', etc.
    set_at          TIMESTAMPTZ NOT NULL,
    prior_target    NUMERIC(18, 4),
    UNIQUE (company_id, analyst, set_at)
);

-- News + sentiment.
CREATE TABLE IF NOT EXISTS news_items (
    id              SERIAL PRIMARY KEY,
    company_id      INT REFERENCES companies(id) ON DELETE SET NULL,
    headline        TEXT NOT NULL,
    url             TEXT,
    source          TEXT,
    published_at    TIMESTAMPTZ NOT NULL,
    sentiment_score REAL,                    -- -1.0 to 1.0, scored by Haiku
    sentiment_at    TIMESTAMPTZ,
    raw_payload     JSONB
);
CREATE INDEX IF NOT EXISTS idx_news_company_published ON news_items (company_id, published_at DESC);

-- Filings (SEC + foreign).
CREATE TABLE IF NOT EXISTS filings (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    form_type       TEXT NOT NULL,            -- '10-K', '10-Q', '8-K', 'EDINET', etc.
    filed_at        TIMESTAMPTZ NOT NULL,
    url             TEXT,
    summary         TEXT,                     -- LLM-extracted summary if processed
    raw_payload     JSONB,
    UNIQUE (company_id, form_type, filed_at)
);

-- Insider transactions (Form 4 in US).
CREATE TABLE IF NOT EXISTS insider_transactions (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    insider_name    TEXT,
    insider_role    TEXT,
    transaction_type TEXT,                    -- 'buy', 'sell', 'option_exercise'
    shares          NUMERIC(20, 4),
    price_per_share NUMERIC(18, 6),
    value_usd       NUMERIC(20, 2),
    transacted_at   DATE NOT NULL,
    filed_at        TIMESTAMPTZ NOT NULL,
    UNIQUE (company_id, insider_name, transacted_at, transaction_type, shares)
);

-- 13F filings.
CREATE TABLE IF NOT EXISTS thirteen_f_holdings (
    id              SERIAL PRIMARY KEY,
    fund_name       TEXT NOT NULL,
    company_id      INT REFERENCES companies(id) ON DELETE SET NULL,
    cusip           TEXT,
    quarter         TEXT NOT NULL,            -- e.g. '2026Q1'
    filed_at        TIMESTAMPTZ,
    shares          NUMERIC(20, 4),
    value_usd       NUMERIC(20, 2),
    pct_of_portfolio REAL,
    change_type     TEXT,                     -- 'new', 'add', 'reduce', 'exit'
    change_pct      REAL,
    UNIQUE (fund_name, cusip, quarter)
);
CREATE INDEX IF NOT EXISTS idx_13f_company_quarter ON thirteen_f_holdings (company_id, quarter);

-- ETF holdings snapshot. Used for daily holdings diff.
CREATE TABLE IF NOT EXISTS etf_holdings (
    id              SERIAL PRIMARY KEY,
    etf_ticker      TEXT NOT NULL,
    company_id      INT REFERENCES companies(id) ON DELETE SET NULL,
    constituent_ticker TEXT NOT NULL,         -- as listed by the ETF, before mapping
    weight_pct      REAL,
    shares          NUMERIC(20, 4),
    as_of           DATE NOT NULL,
    UNIQUE (etf_ticker, constituent_ticker, as_of)
);
CREATE INDEX IF NOT EXISTS idx_etf_holdings_company_asof ON etf_holdings (company_id, as_of DESC);

-- ETF holdings diff: rows where a name was added/removed/weight-changed vs prior day.
CREATE TABLE IF NOT EXISTS etf_diffs (
    id              SERIAL PRIMARY KEY,
    etf_ticker      TEXT NOT NULL,
    company_id      INT REFERENCES companies(id) ON DELETE SET NULL,
    constituent_ticker TEXT NOT NULL,
    diff_type       TEXT NOT NULL,            -- 'add', 'remove', 'weight_change'
    prior_weight_pct REAL,
    new_weight_pct  REAL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Earnings call transcripts (Aiera).
CREATE TABLE IF NOT EXISTS transcripts (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    fiscal_period   TEXT,
    held_at         TIMESTAMPTZ NOT NULL,
    full_text       TEXT,
    summary         TEXT,                     -- LLM summary
    UNIQUE (company_id, held_at)
);

-- Buzzword/theme mention counts per transcript. Drives Thematic Discovery.
CREATE TABLE IF NOT EXISTS transcript_mentions (
    id              SERIAL PRIMARY KEY,
    transcript_id   INT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    term            TEXT NOT NULL,            -- e.g. 'CoWoS', 'HBM', 'liquid cooling', 'transformer lead time'
    count           INT NOT NULL,
    UNIQUE (transcript_id, term)
);

-- Research reports (drop-folder PDFs).
CREATE TABLE IF NOT EXISTS research_reports (
    id              SERIAL PRIMARY KEY,
    publisher       TEXT NOT NULL,            -- 'McKinsey', 'Goldman Sachs', 'SemiAnalysis', etc.
    title           TEXT NOT NULL,
    published_at    DATE,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_path     TEXT,
    summary         TEXT,                     -- LLM extract
    raw_text        TEXT
);

CREATE TABLE IF NOT EXISTS research_report_mentions (
    id              SERIAL PRIMARY KEY,
    report_id       INT NOT NULL REFERENCES research_reports(id) ON DELETE CASCADE,
    company_id      INT REFERENCES companies(id) ON DELETE SET NULL,
    raw_mention     TEXT NOT NULL,
    context_excerpt TEXT,
    sentiment_score REAL
);

-- ============================================================
-- Signal layer
-- ============================================================

-- One row per company per scoring run.
CREATE TABLE IF NOT EXISTS signal_scores (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    scored_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    composite_score REAL,                     -- 0-100
    discovery_strength REAL,                  -- how new / how surprising
    timing_strength REAL,                     -- valuation + revisions + beats + sentiment
    breakdown       JSONB NOT NULL,           -- per-signal contributions for explainability
    one_line_why    TEXT
);
CREATE INDEX IF NOT EXISTS idx_signal_scores_company ON signal_scores (company_id, scored_at DESC);

-- Rapid alert log. One row per alert fired.
CREATE TABLE IF NOT EXISTS rapid_alerts (
    id              SERIAL PRIMARY KEY,
    company_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    alert_type      TEXT NOT NULL,            -- 'thirteen_f_add', 'insider_buy', 'unusual_options', etc.
    fired_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    suppressed      BOOLEAN NOT NULL DEFAULT FALSE,  -- soft-cap dedupe
    payload         JSONB NOT NULL,
    one_line_why    TEXT NOT NULL
);

-- Monthly report log.
CREATE TABLE IF NOT EXISTS monthly_reports (
    id              SERIAL PRIMARY KEY,
    month           DATE NOT NULL UNIQUE,
    sent_at         TIMESTAMPTZ,
    candidates_count INT NOT NULL DEFAULT 0,
    new_names_count INT NOT NULL DEFAULT 0,
    raw_payload     JSONB
);

-- ============================================================
-- Safe-harbor monitor (Swiss Kreisschreiben 36)
-- ============================================================

CREATE TABLE IF NOT EXISTS safe_harbor_log (
    id              SERIAL PRIMARY KEY,
    as_of           DATE NOT NULL,
    turnover_pct_ytd REAL,                    -- (sum of trade values YTD) / portfolio value
    avg_holding_days REAL,
    derivative_exposure_usd NUMERIC(20, 2),
    derivative_purpose_breakdown JSONB,        -- {hedge: $, asymmetric: $, alpha: $}
    debt_financed BOOLEAN NOT NULL DEFAULT FALSE,
    soft_block_engaged BOOLEAN NOT NULL DEFAULT FALSE,
    notes           TEXT,
    UNIQUE (as_of)
);
