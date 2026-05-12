"""Daily price ingest via yfinance. Pulls last N days for every company in the
universe (excluded or not — we still want price history on seed names so the
signal layer has something to work with).

Idempotent: re-running for the same dates upserts.

Run locally:  uv run python -m signal_engine.ingest.prices
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import yfinance as yf

from signal_engine.db import connect
from signal_engine.tickers import yfinance_symbol

log = logging.getLogger(__name__)

LOOKBACK_DAYS = 7   # daily job catches up if we missed a day


def fetch_history(symbol: str, days: int) -> list[tuple[date, float, float, int]]:
    """Return list of (date, close, close, volume). USD conversion happens later."""
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=days + 5)  # buffer for weekends/holidays
    df = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=False)
    rows: list[tuple[date, float, float, int]] = []
    for ts, row in df.iterrows():
        d = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
        close = float(row["Close"]) if row["Close"] == row["Close"] else None  # NaN check
        volume = int(row["Volume"]) if row["Volume"] == row["Volume"] else 0
        if close is None:
            continue
        rows.append((d, close, close, volume))
    return rows


def run() -> dict[str, Any]:
    inserted = 0
    failed: list[str] = []
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, ticker, exchange FROM companies ORDER BY ticker")
        companies = cur.fetchall()
        for c in companies:
            symbol = yfinance_symbol(c["ticker"], c["exchange"])
            try:
                rows = fetch_history(symbol, LOOKBACK_DAYS)
            except Exception as e:
                log.warning("price fetch failed for %s (%s): %s", symbol, c["exchange"], e)
                failed.append(symbol)
                continue
            for d, close_local, close_usd, volume in rows:
                cur.execute(
                    """
                    INSERT INTO prices_daily (company_id, date, close_local, close_usd, volume)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (company_id, date) DO UPDATE SET
                        close_local = EXCLUDED.close_local,
                        close_usd = EXCLUDED.close_usd,
                        volume = EXCLUDED.volume
                    """,
                    (c["id"], d, close_local, close_usd, volume),
                )
                inserted += 1
        conn.commit()
    return {"companies": len(companies), "rows": inserted, "failed": failed}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run()
    print(f"Prices ingest: {result['companies']} companies, {result['rows']} rows")
    if result["failed"]:
        print(f"  failed: {result['failed']}")
