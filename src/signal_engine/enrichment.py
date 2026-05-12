"""Enrichment helpers — pull company context for tickers we don't have stored.

For discovery candidates (names not yet in our universe), we need lightweight
metadata: company name, sector, industry, market cap, business summary. yfinance
provides this via Ticker.info — free, no API key.

In-process LRU cache. Don't bother persisting to DB until the candidate is
actually promoted to the universe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import yfinance as yf

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompanyInfo:
    ticker: str
    name: str | None
    sector: str | None
    industry: str | None
    country: str | None
    market_cap_usd: float | None
    pe_ttm: float | None
    pe_forward: float | None
    business_summary: str | None
    website: str | None


@lru_cache(maxsize=256)
def fetch(ticker: str) -> CompanyInfo:
    """Fetch enrichment data for a ticker. Returns CompanyInfo with None fields
    on failure rather than raising — degrades gracefully if yfinance is flaky."""
    try:
        info = yf.Ticker(ticker).info
    except Exception as e:
        log.warning("yfinance .info failed for %s: %s", ticker, e)
        info = {}
    if not info:
        info = {}
    return CompanyInfo(
        ticker=ticker,
        name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        country=info.get("country"),
        market_cap_usd=info.get("marketCap"),
        pe_ttm=info.get("trailingPE"),
        pe_forward=info.get("forwardPE"),
        business_summary=info.get("longBusinessSummary"),
        website=info.get("website"),
    )
