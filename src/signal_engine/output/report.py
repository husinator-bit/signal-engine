"""Discovery Report composer.

Pulls data from the DB (discovery candidates, recent filings, price moves),
renders the Jinja template, returns HTML + subject line.

Run locally:  uv run python -m signal_engine.output.report > /tmp/report.html
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from signal_engine.config import etfs as etf_config
from signal_engine.db import connect
from signal_engine.scoring.discovery import rank_candidates

TEMPLATE_DIR = Path(__file__).parent / "templates"
INSIDER_WINDOW_DAYS = 14
FILING_WINDOW_DAYS = 14
PRICE_WINDOW_DAYS = 7


def _next_report_num() -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM monthly_reports")
        return cur.fetchone()["n"] + 1


def _insider_filings() -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=INSIDER_WINDOW_DAYS)
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
            LIMIT 30
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
    """Top movers in the watchlist over last PRICE_WINDOW_DAYS, by abs % change."""
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
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("discovery_report.html")

    candidates = rank_candidates(limit=10)
    insider = _insider_filings()
    material = _material_filings()
    moves = _price_moves()
    universe = _universe_count()
    report_num = _next_report_num()
    today = datetime.now(timezone.utc).date()

    html = template.render(
        report_num=report_num,
        report_date=today.strftime("%B %Y"),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        candidates=[asdict(c) for c in candidates],
        candidate_count=len(candidates),
        universe_count=universe,
        etf_count=len(etf_config()),
        insider_filings=insider,
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
    subject, html = compose()
    sys.stderr.write(f"Subject: {subject}\n")
    sys.stdout.write(html)
