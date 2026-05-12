"""Runtime configuration. Secrets read from env. Static config from YAML."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR") or Path(__file__).resolve().parents[2] / "config")


class MissingSecret(RuntimeError):
    pass


def secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingSecret(f"Environment variable {name} is not set")
    return value


@cache
def load_yaml(filename: str) -> dict[str, Any]:
    path = CONFIG_DIR / filename
    with path.open() as f:
        return yaml.safe_load(f)


def universe_seed() -> list[dict[str, Any]]:
    return load_yaml("universe_seed.yaml")["companies"]


def themes() -> list[dict[str, Any]]:
    return load_yaml("themes.yaml")["themes"]


def etfs() -> list[dict[str, Any]]:
    return load_yaml("etfs.yaml")["etfs"]
