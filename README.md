# AI Industry Intelligence Engine

Discovery engine for hidden champions in the AI infrastructure stack. See [SPEC.md](SPEC.md).

## Status

Week 1 of 6 — foundation.

## Quick start

```bash
# Install dependencies (uv-managed)
uv sync

# Run ingest locally
uv run python -m signal_engine.ingest.daily

# Run tests
uv run pytest
```

## Layout

```
src/signal_engine/    Python source
db/schema.sql         Postgres schema (Neon)
scripts/              One-off scripts (seed, manual jobs)
config/               Universe seed, theme tags, ETF list
docs/                 Architecture decisions, runbook
```

## External services required

See [docs/SETUP.md](docs/SETUP.md) for the account-provisioning checklist.
