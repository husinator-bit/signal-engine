"""Map our (ticker, exchange) tuple to vendor-specific symbols.

We use yfinance as the price source. yfinance uses Yahoo's suffix convention:
  TSE  -> .T          (Tokyo)
  TWSE -> .TW         (Taipei)
  KRX  -> .KS         (Korea KOSPI) / .KQ (KOSDAQ — we use .KS for both, yfinance handles it)
  AMS  -> .AS         (Amsterdam)
  XETR -> .DE         (Xetra)
  LSE  -> .L          (London)
  HKEX -> .HK         (Hong Kong)
  SIX  -> .SW         (Swiss)
  NYSE / NASDAQ -> no suffix
"""

from __future__ import annotations

_SUFFIX = {
    "NYSE": "",
    "NASDAQ": "",
    "TSE": ".T",
    "TWSE": ".TW",
    "KRX": ".KS",
    "AMS": ".AS",
    "XETR": ".DE",
    "LSE": ".L",
    "HKEX": ".HK",
    "SIX": ".SW",
}


def yfinance_symbol(ticker: str, exchange: str) -> str:
    suffix = _SUFFIX.get(exchange.upper())
    if suffix is None:
        # Unknown exchange — try ticker bare and let yfinance fail loudly
        return ticker
    return f"{ticker}{suffix}"
