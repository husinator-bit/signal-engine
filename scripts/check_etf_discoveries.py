"""Show ETF constituents that are NOT in our universe — these are the discovery
candidates the Hidden Champion Finder will surface."""

from __future__ import annotations

from signal_engine.db import connect


def main() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT eh.constituent_ticker,
                   COUNT(DISTINCT eh.etf_ticker) AS in_n_etfs,
                   STRING_AGG(DISTINCT eh.etf_ticker, ', ' ORDER BY eh.etf_ticker) AS etfs,
                   ROUND(AVG(eh.weight_pct)::numeric, 2) AS avg_weight,
                   ROUND(MAX(eh.weight_pct)::numeric, 2) AS max_weight
            FROM etf_holdings eh
            LEFT JOIN companies c ON UPPER(c.ticker) = eh.constituent_ticker
            WHERE c.id IS NULL
              AND eh.as_of = (SELECT MAX(as_of) FROM etf_holdings)
            GROUP BY eh.constituent_ticker
            ORDER BY in_n_etfs DESC, max_weight DESC
            """
        )
        rows = cur.fetchall()
    print(f"Discovery candidates (in ETFs but NOT in universe): {len(rows)}")
    print(f"{'TICKER':10s} {'ETFs':>4s}  {'WGT%':>6s}  ETFs")
    print("-" * 60)
    for r in rows[:30]:
        print(f"{r['constituent_ticker']:10s} {r['in_n_etfs']:>4d}  {float(r['max_weight']):>6.2f}  {r['etfs']}")


if __name__ == "__main__":
    main()
