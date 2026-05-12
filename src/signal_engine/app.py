"""Modal app — daily ingest jobs scheduled in the cloud.

Deploy:   modal deploy src/signal_engine/app.py
Run one:  modal run src/signal_engine/app.py::ingest_prices
View:     https://modal.com/apps/husinator-bit/main/signal-engine
"""

from __future__ import annotations

import logging

import modal

# Image: slim Python 3.12 + project deps. We install from pyproject so the image
# matches local dev. We mount the source separately as add_local_python_source.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "anthropic>=0.40.0",
        "httpx>=0.27.0",
        "jinja2>=3.1.0",
        "notion-client>=2.2.0",
        "psycopg[binary]>=3.2.0",
        "pydantic>=2.9.0",
        "pyyaml>=6.0.2",
        "resend>=2.0.0",
        "sqlmodel>=0.0.22",
        "tenacity>=9.0.0",
        "yfinance>=0.2.40",
    )
    .add_local_python_source("signal_engine")
    .add_local_dir(
        "/Users/kaykuehne/Desktop/Business/Investment/AI/signal-engine/config",
        remote_path="/root/config",
    )
)

app = modal.App("signal-engine", image=image)

secret = modal.Secret.from_name("signal-engine")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


# ---------------------------------------------------------------------------
# Scheduled jobs (all times UTC). See SPEC.md for cadence rationale.
# ---------------------------------------------------------------------------

@app.function(secrets=[secret], schedule=modal.Cron("0 4 * * *"), timeout=900)
def ingest_prices() -> dict:
    """Daily price ingest via yfinance. 04:00 UTC."""
    import os
    os.environ.setdefault("CONFIG_DIR", "/root/config")
    _setup_logging()
    from signal_engine.ingest import prices
    result = prices.run()
    print(f"prices: {result}")
    return result


@app.function(secrets=[secret], schedule=modal.Cron("0 6 * * *"), timeout=1800)
def ingest_filings() -> dict:
    """Daily SEC EDGAR filings ingest. 06:00 UTC. Slower because SEC API is slow."""
    import os
    os.environ.setdefault("CONFIG_DIR", "/root/config")
    _setup_logging()
    from signal_engine.ingest import filings
    result = filings.run()
    print(f"filings: {result}")
    return result


@app.function(secrets=[secret], schedule=modal.Cron("30 21 * * *"), timeout=900)
def ingest_etfs() -> dict:
    """Daily ETF holdings + diffs. 21:30 UTC (post-US close)."""
    import os
    os.environ.setdefault("CONFIG_DIR", "/root/config")
    _setup_logging()
    from signal_engine.ingest import etfs
    result = etfs.run()
    print(f"etfs: {result}")
    return result


# ---------------------------------------------------------------------------
# Manual entrypoints — run via `modal run ...` for ad-hoc testing.
# ---------------------------------------------------------------------------

@app.function(secrets=[secret], timeout=900)
def run_prices() -> dict:
    """Manual trigger for ingest_prices."""
    import os
    os.environ.setdefault("CONFIG_DIR", "/root/config")
    _setup_logging()
    from signal_engine.ingest import prices
    return prices.run()


@app.function(secrets=[secret], timeout=1800)
def run_filings() -> dict:
    import os
    os.environ.setdefault("CONFIG_DIR", "/root/config")
    _setup_logging()
    from signal_engine.ingest import filings
    return filings.run()


@app.function(secrets=[secret], timeout=900)
def run_etfs() -> dict:
    import os
    os.environ.setdefault("CONFIG_DIR", "/root/config")
    _setup_logging()
    from signal_engine.ingest import etfs
    return etfs.run()


# ---------------------------------------------------------------------------
# Report layer
# ---------------------------------------------------------------------------

@app.function(secrets=[secret], schedule=modal.Cron("0 6 1 * *"), timeout=600)
def send_monthly_discovery_report() -> dict:
    """Compose + send Discovery Report on the 1st of every month, 06:00 UTC
    (= 07:00 CET). Triggered automatically; do not call directly."""
    import os
    os.environ.setdefault("CONFIG_DIR", "/root/config")
    _setup_logging()
    from signal_engine.output import email, report
    subject, html = report.compose()
    response = email.send(subject, html)
    report.record_sent(candidates_count=10)
    return {"sent": True, "id": response.get("id"), "subject": subject}


@app.function(secrets=[secret], timeout=600)
def run_report() -> dict:
    """Manual trigger for the Discovery Report. Sends to USER_EMAIL."""
    import os
    os.environ.setdefault("CONFIG_DIR", "/root/config")
    _setup_logging()
    from signal_engine.output import email, report
    subject, html = report.compose()
    response = email.send(subject, html)
    report.record_sent(candidates_count=10)
    return {"sent": True, "id": response.get("id"), "subject": subject}


@app.local_entrypoint()
def smoke() -> None:
    """Local smoke test: triggers all three ingest jobs in the cloud."""
    print("Smoke-testing all three ingest jobs in Modal cloud...")
    p = run_prices.remote()
    print(f"  prices: {p}")
    e = run_etfs.remote()
    print(f"  etfs: {e}")
    f = run_filings.remote()
    print(f"  filings: {f}")
