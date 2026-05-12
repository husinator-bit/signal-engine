"""One-off cleanup: remove the 432/KRX row that was created by a YAML octal-parse
bug (the ticker '000660' was parsed as octal -> 432).

After running this, re-run seed_universe.py to insert the corrected row.
"""

from __future__ import annotations

from signal_engine.db import connect


def main() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM companies WHERE ticker = '432' AND exchange = 'KRX'")
        print(f"Deleted {cur.rowcount} bad row(s)")
        conn.commit()


if __name__ == "__main__":
    main()
