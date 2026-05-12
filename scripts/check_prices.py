"""Spot-check the prices_daily table."""

from __future__ import annotations

from signal_engine.db import connect


def main() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.ticker, c.exchange, COUNT(p.date) AS n, MAX(p.date) AS latest,
                   MAX(p.close_local) AS last_close
            FROM companies c
            LEFT JOIN prices_daily p ON p.company_id = c.id
            GROUP BY c.id, c.ticker, c.exchange
            ORDER BY n DESC, c.ticker
            """
        )
        rows = cur.fetchall()
    print(f"{'TICKER':10s} {'EXCHG':6s} {'BARS':>5s}  {'LATEST':12s} {'CLOSE':>12s}")
    print("-" * 50)
    for r in rows:
        latest = str(r["latest"]) if r["latest"] else "—"
        close = f"{r['last_close']:.2f}" if r["last_close"] else "—"
        print(f"{r['ticker']:10s} {r['exchange']:6s} {r['n']:>5d}  {latest:12s} {close:>12s}")


if __name__ == "__main__":
    main()
