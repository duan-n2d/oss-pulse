"""Paths and tracked-repo configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("OSS_PULSE_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
STATE_DIR = DATA_DIR / "state"
WAREHOUSE = Path(os.environ.get("OSS_PULSE_WAREHOUSE", DATA_DIR / "warehouse.duckdb"))
CONFIG_FILE = ROOT / "config" / "repos.yml"


@dataclass(frozen=True)
class Repo:
    name: str
    pypi: str | None

    @property
    def owner(self) -> str:
        return self.name.split("/", 1)[0]

    @property
    def short(self) -> str:
        return self.name.split("/", 1)[1]


@dataclass(frozen=True)
class Config:
    repos: list[Repo]
    window_days: int


def load_config(path: Path = CONFIG_FILE) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    repos = [Repo(name=r["name"], pypi=r.get("pypi")) for r in raw["repos"]]
    names = [r.name for r in repos]
    if len(names) != len(set(names)):
        raise ValueError("duplicate repo in config")
    return Config(repos=repos, window_days=int(raw.get("window_days", 365)))
