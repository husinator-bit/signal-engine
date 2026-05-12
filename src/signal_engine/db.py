"""Postgres connection management."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from signal_engine.config import secret


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    url = secret("DATABASE_URL")
    with psycopg.connect(url, row_factory=dict_row, autocommit=False) as conn:
        yield conn
