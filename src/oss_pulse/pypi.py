"""Land daily PyPI downloads from pypistats.org (last ~180 days, mirrors excluded).

pypistats returns the full rolling window on every call, so each run overwrites one
file per run date; staging keeps the most recent observation of each (package, day).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime

import pyarrow as pa
import requests

from .config import RAW_DIR, Repo
from .landing import write_partition

log = logging.getLogger(__name__)

URL = "https://pypistats.org/api/packages/{package}/overall"

SCHEMA = pa.schema(
    [
        ("package", pa.string()),
        ("repo", pa.string()),
        ("download_date", pa.date32()),
        ("downloads", pa.int64()),
        ("ingested_at", pa.timestamp("us", tz="UTC")),
    ]
)


def fetch_package(package: str, session: requests.Session, retries: int = 5) -> list[dict]:
    delay = 5.0
    for _ in range(retries):
        resp = session.get(URL.format(package=package), params={"mirrors": "false"}, timeout=60)
        if resp.status_code == 429:
            time.sleep(delay)
            delay *= 2
            continue
        resp.raise_for_status()
        return [
            row for row in resp.json()["data"] if row["category"] == "without_mirrors"
        ]
    raise RuntimeError(f"pypistats rate-limited {package} {retries} times")


def land_downloads(repos: list[Repo], run_date: date, session: requests.Session | None = None) -> int:
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", "oss-pulse (+https://github.com/duan-n2d/oss-pulse)")
    now = datetime.now(UTC).replace(microsecond=0)
    rows: list[dict] = []
    for repo in repos:
        if not repo.pypi:
            continue
        for item in fetch_package(repo.pypi, session):
            rows.append(
                {
                    "package": repo.pypi,
                    "repo": repo.name,
                    "download_date": date.fromisoformat(item["date"]),
                    "downloads": int(item["downloads"]),
                    "ingested_at": now,
                }
            )
        time.sleep(1)  # pypistats asks clients to be gentle
    path = RAW_DIR / "pypi_downloads" / f"run_date={run_date.isoformat()}.parquet"
    write_partition(pa.Table.from_pylist(rows, schema=SCHEMA), path)
    log.info("pypi: %d package-days", len(rows))
    return len(rows)
