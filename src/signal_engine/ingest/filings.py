"""SEC EDGAR filings ingest. Free, direct from data.sec.gov.

Strategy:
- Fetch SEC's full ticker -> CIK map once per run (cached in-memory, but a daily
  job is fresh enough).
- For each US-listed company, fetch /submissions/CIK{cik}.json which contains
  the last 1000 filings.
- Filter for form types we care about (10-K, 10-Q, 8-K, 4) and upsert metadata.
- We do NOT download or parse content here — that's a later step.

SEC requires a User-Agent identifying the operator. They rate-limit at 10
requests/sec. We're well under that for ~25 names daily.

Run locally:  uv run python -m signal_engine.ingest.filings
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from signal_engine.config import secret
from signal_engine.db import connect

log = logging.getLogger(__name__)

WANTED_FORMS = {"10-K", "10-Q", "8-K", "4", "13F-HR", "13F-HR/A"}
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX"}


def _user_agent() -> str:
    email = os.environ.get("USER_EMAIL", "ops@example.com")
    return f"signal-engine ({email})"


def fetch_ticker_to_cik() -> dict[str, int]:
    """Return ticker (upper) -> CIK."""
    headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=30.0) as client:
        r = client.get(TICKER_MAP_URL)
        r.raise_for_status()
        data = r.json()
    return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}


def fetch_recent_filings(cik: int) -> list[dict[str, Any]]:
    """Fetch the recent-filings block for a CIK. Returns a list of normalized dicts."""
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=30.0) as client:
        r = client.get(url)
        r.raise_for_status()
        data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accession = recent.get("accessionNumber", [])
    primary_doc = recent.get("primaryDocument", [])
    out: list[dict[str, Any]] = []
    for i in range(len(forms)):
        if forms[i] not in WANTED_FORMS:
            continue
        acc = accession[i].replace("-", "")
        doc = primary_doc[i] if i < len(primary_doc) else ""
        out.append(
            {
                "form_type": forms[i],
                "filed_at": datetime.fromisoformat(dates[i]).replace(tzinfo=timezone.utc),
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}",
                "accession": accession[i],
            }
        )
    return out


def run() -> dict[str, Any]:
    ticker_to_cik = fetch_ticker_to_cik()
    log.info("Loaded %d ticker→CIK mappings", len(ticker_to_cik))

    inserted = 0
    skipped_no_cik = 0
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, ticker, exchange, name FROM companies WHERE exchange = ANY(%s)",
            (list(US_EXCHANGES),),
        )
        us_companies = cur.fetchall()

        for c in us_companies:
            cik = ticker_to_cik.get(c["ticker"].upper())
            if cik is None:
                log.info("No CIK for %s, skipping", c["ticker"])
                skipped_no_cik += 1
                continue
            try:
                filings = fetch_recent_filings(cik)
            except Exception as e:
                log.warning("filing fetch failed for %s (CIK %s): %s", c["ticker"], cik, e)
                continue
            for f in filings:
                cur.execute(
                    """
                    INSERT INTO filings (company_id, form_type, filed_at, url, raw_payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (company_id, form_type, filed_at) DO NOTHING
                    """,
                    (c["id"], f["form_type"], f["filed_at"], f["url"], '{"accession": "' + f["accession"] + '"}'),
                )
                inserted += cur.rowcount
            time.sleep(0.15)  # SEC asks for <=10 req/s; we use ~6/s to be polite
        conn.commit()
    return {
        "us_companies": len(us_companies),
        "no_cik": skipped_no_cik,
        "filings_inserted": inserted,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run()
    print(
        f"Filings ingest: {result['us_companies']} US companies, "
        f"{result['filings_inserted']} new filings, "
        f"{result['no_cik']} with no CIK match"
    )
