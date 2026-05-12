"""Discovery Report composer.

Pulls data from the DB (discovery candidates, recent filings, price moves),
enriches candidates with yfinance company info and LLM-generated narratives,
parses Form 4 insider transactions on-demand, renders the Jinja template.

Run locally:  uv run python -m signal_engine.output.report > /tmp/report.html
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from signal_engine.config import etfs as etf_config
from signal_engine.db import connect
from signal_engine.enrichment import fetch as fetch_company_info
from signal_engine.form4 import fetch_and_parse
from signal_engine.llm import generate_narrative
from signal_engine.scoring.discovery import DiscoveryCandidate, rank_candidates

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
INSIDER_WINDOW_DAYS = 14
FILING_WINDOW_DAYS = 14
PRICE_WINDOW_DAYS = 7
TOP_CANDIDATES_FOR_NARRATIVE = 5         # LLM narrative for top N only
TOTAL_CANDIDATES_SHOWN = 10              # Remaining shown as short list
MAX_INSIDER_FILINGS_TO_PARSE = 10        # cap SEC fetches per report


@dataclass
class EnrichedCandidate:
    ticker: str
    name: str
    sector: str
    industry: str
    country: str
    market_cap_display: str
    pe_display: str
    in_etfs: list[str]
    max_weight_pct: float
    theme_focuses: list[str]
    composite_score: float
    one_line_why: str
    narrative: str        # multi-paragraph; "" if not generated


@dataclass
class ParsedInsiderFiling:
    ticker: str
    filed_date: str
    transacted_date: str
    insider_name: str
    insider_role: str
    transaction_type: str
    shares: float
    price_per_share: float | None
    value_usd: float | None
    url: str


def _next_report_num() -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM monthly_reports")
        return cur.fetchone()["n"] + 1


def _format_mcap(usd: float | None) -> str:
    if not usd:
        return "n/a"
    if usd >= 1e12:
        return f"${usd / 1e12:.1f}T"
    if usd >= 1e9:
        return f"${usd / 1e9:.1f}B"
    if usd >= 1e6:
        return f"${usd / 1e6:.0f}M"
    return f"${usd:,.0f}"


def _format_pe(ttm: float | None, fwd: float | None) -> str:
    if ttm and fwd:
        return f"P/E {ttm:.1f} (fwd {fwd:.1f})"
    if ttm:
        return f"P/E {ttm:.1f}"
    if fwd:
        return f"P/E fwd {fwd:.1f}"
    return "P/E n/a"


def _enrich_candidates(candidates: list[DiscoveryCandidate]) -> list[EnrichedCandidate]:
    enriched: list[EnrichedCandidate] = []
    for i, c in enumerate(candidates):
        info = fetch_company_info(c.ticker)
        narrative = ""
        if i < TOP_CANDIDATES_FOR_NARRATIVE:
            narrative = generate_narrative(c, info)
        enriched.append(
            EnrichedCandidate(
                ticker=c.ticker,
                name=info.name or "—",
                sector=info.sector or "—",
                industry=info.industry or "—",
                country=info.country or "—",
                market_cap_display=_format_mcap(info.market_cap_usd),
                pe_display=_format_pe(info.pe_ttm, info.pe_forward),
                in_etfs=c.in_etfs,
                max_weight_pct=c.max_weight_pct,
                theme_focuses=c.theme_focuses,
                composite_score=c.composite_score,
                one_line_why=c.one_line_why,
                narrative=narrative,
            )
        )
    return enriched


def _insider_filings() -> list[ParsedInsiderFiling]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=INSIDER_WINDOW_DAYS)
    parsed: list[ParsedInsiderFiling] = []
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.ticker, f.form_type, f.filed_at, f.url
            FROM filings f
            JOIN companies c ON c.id = f.company_id
            WHERE f.form_type = '4'
              AND f.filed_at >= %s
              AND c.is_excluded = TRUE
            ORDER BY f.filed_at DESC
            LIMIT %s
            """,
            (cutoff, MAX_INSIDER_FILINGS_TO_PARSE),
        )
        rows = cur.fetchall()
    for r in rows:
        txns = fetch_and_parse(r["url"])
        if not txns:
            continue
        # Take the largest non-derivative transaction per filing
        txn = max(txns, key=lambda t: t.value_usd or 0)
        parsed.append(
            ParsedInsiderFiling(
                ticker=r["ticker"],
                filed_date=r["filed_at"].strftime("%Y-%m-%d"),
                transacted_date=txn.transacted_at.strftime("%Y-%m-%d"),
                insider_name=txn.insider_name,
                insider_role=txn.insider_role,
                transaction_type=txn.transaction_type,
                shares=txn.shares,
                price_per_share=txn.price_per_share,
                value_usd=txn.value_usd,
                url=r["url"],
            )
        )
    return parsed


def _material_filings() -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=FILING_WINDOW_DAYS)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.ticker, f.form_type, f.filed_at, f.url
            FROM filings f
            JOIN companies c ON c.id = f.company_id
            WHERE f.form_type IN ('10-K', '10-Q', '8-K')
              AND f.filed_at >= %s
              AND c.is_excluded = TRUE
            ORDER BY f.filed_at DESC
            LIMIT 20
            """,
            (cutoff,),
        )
        return [
            {
                "ticker": r["ticker"],
                "form_type": r["form_type"],
                "filed_date": r["filed_at"].strftime("%Y-%m-%d"),
                "url": r["url"],
            }
            for r in cur.fetchall()
        ]


def _price_moves() -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH bounds AS (
                SELECT company_id,
                       MIN(date) AS first_date,
                       MAX(date) AS last_date
                FROM prices_daily
                WHERE date >= CURRENT_DATE - %s::int
                GROUP BY company_id
            ),
            pair AS (
                SELECT b.company_id,
                       p1.close_local AS first_close,
                       p2.close_local AS last_close
                FROM bounds b
                JOIN prices_daily p1 ON p1.company_id = b.company_id AND p1.date = b.first_date
                JOIN prices_daily p2 ON p2.company_id = b.company_id AND p2.date = b.last_date
            )
            SELECT ticker, exchange, pct_change FROM (
              SELECT c.ticker, c.exchange,
                     CASE WHEN pair.first_close > 0
                          THEN ((pair.last_close - pair.first_close) / pair.first_close * 100)
                          ELSE 0 END AS pct_change
              FROM pair
              JOIN companies c ON c.id = pair.company_id
              WHERE c.is_excluded = TRUE
            ) m
            ORDER BY ABS(pct_change) DESC
            LIMIT 10
            """,
            (PRICE_WINDOW_DAYS,),
        )
        return [
            {
                "ticker": r["ticker"],
                "exchange": r["exchange"],
                "pct_change": float(r["pct_change"]),
            }
            for r in cur.fetchall()
        ]


def _universe_count() -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM companies")
        return cur.fetchone()["n"]


def compose() -> tuple[str, str]:
    """Return (subject, html)."""
    log.info("Composing Discovery Report")

    raw_candidates = rank_candidates(limit=TOTAL_CANDIDATES_SHOWN)
    log.info("Enriching top %d candidates with LLM narrative", TOP_CANDIDATES_FOR_NARRATIVE)
    candidates = _enrich_candidates(raw_candidates)
    log.info("Parsing recent Form 4 filings")
    insider = _insider_filings()
    material = _material_filings()
    moves = _price_moves()
    universe = _universe_count()
    report_num = _next_report_num()
    today = datetime.now(timezone.utc).date()

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("discovery_report.html")
    html = template.render(
        report_num=report_num,
        report_date=today.strftime("%B %Y"),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        top_candidates=[asdict(c) for c in candidates[:TOP_CANDIDATES_FOR_NARRATIVE]],
        also_candidates=[asdict(c) for c in candidates[TOP_CANDIDATES_FOR_NARRATIVE:]],
        candidate_count=len(candidates),
        universe_count=universe,
        etf_count=len(etf_config()),
        insider_filings=[asdict(f) for f in insider],
        insider_window_days=INSIDER_WINDOW_DAYS,
        material_filings=material,
        filing_window_days=FILING_WINDOW_DAYS,
        price_moves=moves,
        price_window_days=PRICE_WINDOW_DAYS,
    )
    subject = f"AI Signal Engine — Discovery Report #{report_num} — {today.strftime('%b %Y')}"
    return subject, html


def record_sent(candidates_count: int) -> None:
    """Write a monthly_reports row marking this report as sent."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO monthly_reports (month, sent_at, candidates_count, new_names_count, raw_payload)
            VALUES (DATE_TRUNC('month', CURRENT_DATE)::date, NOW(), %s, %s, %s::jsonb)
            ON CONFLICT (month) DO UPDATE SET
                sent_at = EXCLUDED.sent_at,
                candidates_count = EXCLUDED.candidates_count
            """,
            (candidates_count, candidates_count, '{}'),
        )
        conn.commit()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    subject, html = compose()
    sys.stderr.write(f"Subject: {subject}\n")
    sys.stdout.write(html)
