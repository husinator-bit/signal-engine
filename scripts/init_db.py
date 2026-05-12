"""Apply db/schema.sql to the configured database.

Idempotent — all CREATE TABLE statements use IF NOT EXISTS.

Run:  uv run python scripts/init_db.py
"""

from __future__ import annotations

from pathlib import Path

from signal_engine.db import connect

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


def main() -> None:
    sql = SCHEMA_PATH.read_text()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print(f"Applied schema from {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
