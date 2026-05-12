"""ETF holdings ingest. Pulls daily top-holdings for the ETFs in config/etfs.yaml
via yfinance.funds_data, computes diffs vs prior snapshot, and stores both.

This is the discovery layer's primary signal source:
- New names appearing in any tracked ETF = potential candidate
- Weight increases = funds adding conviction

yfinance's funds_data.top_holdings returns the top ~10 names per ETF. That's
limited but reliable. For broader coverage we'll add issuer-direct scrapers in
v1.5 (week 5).

Run locally:  uv run python -m signal_engine.ingest.etfs
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import yfinance as yf

from signal_engine.config import etfs as etf_config
from signal_engine.db import connect

log = logging.getLogger(__name__)


def fetch_top_holdings(etf_ticker: str) -> list[tuple[str, float]]:
    """Return list of (constituent_ticker, weight_pct) for an ETF."""
    try:
        df = yf.Ticker(etf_ticker).funds_data.top_holdings
    except Exception as e:
        log.warning("yfinance top_holdings failed for %s: %s", etf_ticker, e)
        return []
    if df is None or df.empty:
        return []
    rows: list[tuple[str, float]] = []
    # yfinance returns a DataFrame indexed by ticker (Symbol) with columns Holding Percent, Name
    for symbol, row in df.iterrows():
        try:
            pct = float(row.get("Holding Percent", 0)) * 100
        except (TypeError, ValueError):
            continue
        rows.append((str(symbol).upper(), pct))
    return rows


def run() -> dict[str, Any]:
    today = date.today()
    holdings_inserted = 0
    diffs_inserted = 0

    with connect() as conn, conn.cursor() as cur:
        for etf in etf_config():
            etf_ticker = etf["ticker"]
            holdings = fetch_top_holdings(etf_ticker)
            if not holdings:
                log.info("No holdings for %s, skipping", etf_ticker)
                continue
            log.info("%s: %d holdings", etf_ticker, len(holdings))

            # Fetch prior snapshot to compute diffs
            cur.execute(
                """
                SELECT constituent_ticker, weight_pct, as_of FROM etf_holdings
                WHERE etf_ticker = %s
                  AND as_of = (SELECT MAX(as_of) FROM etf_holdings WHERE etf_ticker = %s AND as_of < %s)
                """,
                (etf_ticker, etf_ticker, today),
            )
            prior = {r["constituent_ticker"]: r["weight_pct"] for r in cur.fetchall()}

            # Map constituent ticker -> company_id (best-effort match by ticker only)
            ticker_to_id: dict[str, int | None] = {}
            for ct, _ in holdings:
                cur.execute(
                    "SELECT id FROM companies WHERE UPPER(ticker) = %s LIMIT 1",
                    (ct,),
                )
                row = cur.fetchone()
                ticker_to_id[ct] = row["id"] if row else None

            # Upsert today's holdings
            new_today: dict[str, float] = {}
            for ct, pct in holdings:
                cur.execute(
                    """
                    INSERT INTO etf_holdings (etf_ticker, company_id, constituent_ticker, weight_pct, as_of)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (etf_ticker, constituent_ticker, as_of) DO UPDATE SET
                        weight_pct = EXCLUDED.weight_pct,
                        company_id = EXCLUDED.company_id
                    """,
                    (etf_ticker, ticker_to_id[ct], ct, pct, today),
                )
                holdings_inserted += 1
                new_today[ct] = pct

            # Diff vs prior snapshot
            if prior:
                # Adds: in today, not in prior
                for ct, pct in new_today.items():
                    if ct not in prior:
                        cur.execute(
                            """
                            INSERT INTO etf_diffs (etf_ticker, company_id, constituent_ticker,
                                                   diff_type, prior_weight_pct, new_weight_pct)
                            VALUES (%s, %s, %s, 'add', NULL, %s)
                            """,
                            (etf_ticker, ticker_to_id[ct], ct, pct),
                        )
                        diffs_inserted += 1
                # Removes: in prior, not today
                for ct, prior_pct in prior.items():
                    if ct not in new_today:
                        cur.execute(
                            "SELECT id FROM companies WHERE UPPER(ticker) = %s LIMIT 1",
                            (ct,),
                        )
                        row = cur.fetchone()
                        company_id = row["id"] if row else None
                        cur.execute(
                            """
                            INSERT INTO etf_diffs (etf_ticker, company_id, constituent_ticker,
                                                   diff_type, prior_weight_pct, new_weight_pct)
                            VALUES (%s, %s, %s, 'remove', %s, NULL)
                            """,
                            (etf_ticker, company_id, ct, prior_pct),
                        )
                        diffs_inserted += 1
                # Significant weight changes (>= 1pp)
                for ct, pct in new_today.items():
                    if ct in prior and abs(pct - prior[ct]) >= 1.0:
                        cur.execute(
                            """
                            INSERT INTO etf_diffs (etf_ticker, company_id, constituent_ticker,
                                                   diff_type, prior_weight_pct, new_weight_pct)
                            VALUES (%s, %s, %s, 'weight_change', %s, %s)
                            """,
                            (etf_ticker, ticker_to_id[ct], ct, prior[ct], pct),
                        )
                        diffs_inserted += 1
        conn.commit()

    return {
        "etfs": len(etf_config()),
        "holdings_rows": holdings_inserted,
        "diffs": diffs_inserted,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run()
    print(f"ETF ingest: {result['etfs']} ETFs, {result['holdings_rows']} holdings rows, {result['diffs']} diffs")
