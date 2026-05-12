"""Seed the universe with the names from config/universe_seed.yaml and themes.yaml.

All seed companies are marked is_excluded=TRUE so the Hidden Champion Finder
cannot re-surface them as "discoveries." Operator can flip the flag manually
in Notion later if a name should be re-eligible.

Idempotent.

Run:  uv run python scripts/seed_universe.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from signal_engine.config import etfs, themes, universe_seed
from signal_engine.db import connect


def main() -> None:
    now = datetime.now(timezone.utc)
    with connect() as conn, conn.cursor() as cur:
        # Themes
        for t in themes():
            cur.execute(
                """
                INSERT INTO themes (slug, name, bottleneck_layer)
                VALUES (%s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    bottleneck_layer = EXCLUDED.bottleneck_layer
                """,
                (t["slug"], t["name"], t.get("bottleneck_layer")),
            )
        # Companies
        for c in universe_seed():
            cur.execute(
                """
                INSERT INTO companies (
                    ticker, exchange, name, is_excluded, excluded_at,
                    excluded_reason, discovered_via, last_seen_at
                )
                VALUES (%s, %s, %s, TRUE, %s, 'seed', 'seed', %s)
                ON CONFLICT (ticker, exchange) DO UPDATE SET
                    name = EXCLUDED.name,
                    last_seen_at = EXCLUDED.last_seen_at
                RETURNING id
                """,
                (c["ticker"], c["exchange"], c["name"], now, now),
            )
            company_id = cur.fetchone()["id"]
            for theme_slug in c.get("themes", []):
                cur.execute("SELECT id FROM themes WHERE slug = %s", (theme_slug,))
                row = cur.fetchone()
                if not row:
                    print(f"  ! unknown theme '{theme_slug}' for {c['ticker']}, skipping")
                    continue
                cur.execute(
                    """
                    INSERT INTO company_themes (company_id, theme_id, weight)
                    VALUES (%s, %s, 1.0)
                    ON CONFLICT (company_id, theme_id) DO NOTHING
                    """,
                    (company_id, row["id"]),
                )
        conn.commit()
        # Counts for confirmation
        cur.execute("SELECT COUNT(*) AS n FROM companies")
        n_companies = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM themes")
        n_themes = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM company_themes")
        n_links = cur.fetchone()["n"]
    print(f"Seeded: {n_companies} companies, {n_themes} themes, {n_links} links")
    print(f"ETFs tracked (from config, not yet in DB): {len(etfs())}")


if __name__ == "__main__":
    main()
