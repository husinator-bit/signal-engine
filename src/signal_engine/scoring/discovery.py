"""Rank discovery candidates from ETF holdings.

A discovery candidate is a name appearing in ≥1 tracked ETF that is NOT already
in our universe (or that is in the universe but flagged is_excluded=FALSE — i.e.
it was discovered previously and not marked-as-known).

Scoring components (v0 — only ETF signal):
  - cross_etf: count of distinct ETFs holding this name (more = stronger)
  - max_weight: highest weight across all ETFs (proxy for conviction)
  - theme_breadth: count of distinct theme-focuses of the ETFs holding it
    (e.g. a name in both GRID and BOTZ has cross-theme exposure)

Composite: cross_etf * 10 + max_weight + theme_breadth * 5
Bounded 0-100 by capping cross_etf at 5 and theme_breadth at 3.

Later (week 2+) we will add 13F adds, insider buying, transcript mentions,
and analyst coverage initiations as additional discovery signals.
"""

from __future__ import annotations

from dataclasses import dataclass

from signal_engine.config import etfs as etf_config
from signal_engine.db import connect


@dataclass
class DiscoveryCandidate:
    ticker: str
    in_etfs: list[str]
    max_weight_pct: float
    avg_weight_pct: float
    theme_focuses: list[str]
    composite_score: float
    one_line_why: str


def _etf_focus_map() -> dict[str, str]:
    return {etf["ticker"]: etf.get("focus", "unknown") for etf in etf_config()}


def rank_candidates(limit: int = 20) -> list[DiscoveryCandidate]:
    focus_map = _etf_focus_map()

    with connect() as conn, conn.cursor() as cur:
        # Strip Yahoo exchange suffix (e.g. "000660.KS" -> "000660") before joining
        # to companies, so a name doesn't surface as "new" just because the source
        # used a different identifier format.
        cur.execute(
            """
            SELECT eh.constituent_ticker,
                   ARRAY_AGG(DISTINCT eh.etf_ticker ORDER BY eh.etf_ticker) AS in_etfs,
                   MAX(eh.weight_pct) AS max_w,
                   AVG(eh.weight_pct) AS avg_w
            FROM etf_holdings eh
            LEFT JOIN companies c
              ON UPPER(c.ticker) = SPLIT_PART(eh.constituent_ticker, '.', 1)
             AND c.is_excluded = TRUE
            WHERE c.id IS NULL
              AND eh.as_of = (SELECT MAX(as_of) FROM etf_holdings)
            GROUP BY eh.constituent_ticker
            ORDER BY COUNT(DISTINCT eh.etf_ticker) DESC, MAX(eh.weight_pct) DESC
            """
        )
        rows = cur.fetchall()

    candidates: list[DiscoveryCandidate] = []
    for r in rows:
        in_etfs: list[str] = list(r["in_etfs"])
        focuses = sorted({focus_map.get(e, "unknown") for e in in_etfs})
        cross_etf = min(len(in_etfs), 5)
        theme_breadth = min(len(focuses), 3)
        max_w = float(r["max_w"])
        composite = min(100.0, cross_etf * 10 + max_w + theme_breadth * 5)

        # Deterministic one-line "why"
        if len(in_etfs) >= 3:
            why = f"In {len(in_etfs)} tracked ETFs ({', '.join(in_etfs[:3])}...), max weight {max_w:.1f}%."
        elif theme_breadth >= 2:
            why = f"Cross-theme exposure ({'/'.join(focuses)}) at {max_w:.1f}% weight in {in_etfs[0]}."
        else:
            why = f"Held by {in_etfs[0]} ({focus_map.get(in_etfs[0], '?')}) at {max_w:.1f}% weight."

        candidates.append(
            DiscoveryCandidate(
                ticker=r["constituent_ticker"],
                in_etfs=in_etfs,
                max_weight_pct=max_w,
                avg_weight_pct=float(r["avg_w"]),
                theme_focuses=focuses,
                composite_score=composite,
                one_line_why=why,
            )
        )

    candidates.sort(key=lambda c: c.composite_score, reverse=True)
    return candidates[:limit]


if __name__ == "__main__":
    cs = rank_candidates(limit=15)
    print(f"Top {len(cs)} discovery candidates:")
    print(f"  {'TICKER':12s} {'SCORE':>6s}  WHY")
    for c in cs:
        print(f"  {c.ticker:12s} {c.composite_score:>6.1f}  {c.one_line_why}")
