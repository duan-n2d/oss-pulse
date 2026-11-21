"""Write a small deterministic landing zone for CI, through the real landing code.

GraphQL-shaped PR nodes go through `github_prs.pr_record`, a gzipped GH Archive hour
goes through `gharchive.land_hour`, so CI exercises the same code paths as the daily
job without calling any API. Usage:

    OSS_PULSE_DATA_DIR=build/fixture OSS_PULSE_SALT=... python scripts/make_fixture.py
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa

from oss_pulse import gharchive, github_prs
from oss_pulse.config import RAW_DIR
from oss_pulse.landing import write_bot_keys, write_partition
from oss_pulse.privacy import get_salt
from oss_pulse.pypi import SCHEMA as PYPI_SCHEMA

AS_OF = date(2026, 6, 30)
REPOS = {"acme/engine": "acme-engine", "acme/js": None}
PEOPLE = [f"dev{i}" for i in range(12)]
MAINTAINERS = {"dev0", "dev1"}


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def pr_node(rng: random.Random, number: int, created: datetime) -> dict:
    author = rng.choice(PEOPLE)
    reviewer = rng.choice(sorted(MAINTAINERS - {author}) or ["dev2"])
    responded = rng.random() < 0.85
    first = created + timedelta(hours=rng.lognormvariate(2.5, 1.2))
    merged = responded and rng.random() < 0.7 and first < datetime(2026, 6, 29, tzinfo=UTC)
    closed = merged or (rng.random() < 0.15)
    end = first + timedelta(hours=rng.uniform(1, 72))
    association = (
        "MEMBER"
        if author in MAINTAINERS
        else rng.choice(["CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "NONE"])
    )
    actor = lambda login, t="User": {"__typename": t, "login": login}  # noqa: E731
    return {
        "number": number,
        "createdAt": _iso(created),
        "updatedAt": _iso(max(created, end if closed else first)),
        "mergedAt": _iso(end) if merged else None,
        "closedAt": _iso(end) if closed else None,
        "isDraft": rng.random() < 0.05,
        "state": "MERGED" if merged else ("CLOSED" if closed else "OPEN"),
        "authorAssociation": association,
        "additions": rng.randint(1, 800),
        "deletions": rng.randint(0, 300),
        "changedFiles": rng.randint(1, 20),
        "author": actor(author),
        "mergedBy": actor(reviewer) if merged else None,
        "reviews": {
            "nodes": [{"submittedAt": _iso(first), "state": "APPROVED", "author": actor(reviewer)}]
            if responded
            else []
        },
        "comments": {
            "nodes": [
                {
                    "createdAt": _iso(created + timedelta(minutes=2)),
                    "author": actor("codecov", "Bot"),
                },
                {"createdAt": _iso(created + timedelta(minutes=5)), "author": actor(author)},
            ]
        },
    }


def write_prs(salt: str, rng: random.Random, repos: list[str], span_days: float, run: str) -> None:
    ingested = datetime(2026, 6, 30, 6, tzinfo=UTC)
    for repo in repos:
        nodes = []
        for number in range(1, 241):
            created = datetime(2025, 7, 1, tzinfo=UTC) + timedelta(
                days=rng.uniform(0, span_days), hours=rng.uniform(0, 24)
            )
            nodes.append(pr_node(rng, number, created))
        records = [github_prs.pr_record(repo, n, salt, ingested) for n in nodes]
        path = github_prs.repo_partition_dir(repo) / f"run={run}.parquet"
        write_partition(pa.Table.from_pylist(records, schema=github_prs.PR_SCHEMA), path)


def write_repos(repos: list[str], label: str) -> None:
    rows = []
    for i, repo in enumerate(repos):
        rows.append(
            {
                "repo": repo,
                "description": f"fixture {repo}",
                "repo_created_at": datetime(2020, 1, 1, tzinfo=UTC),
                "is_archived": False,
                "stars": 1000 * (i + 1),
                "forks": 100 * (i + 1),
                "license": "MIT",
                "primary_language": "Python",
                "default_branch": "main",
                "observed_at": datetime(2026, 6, 30, 6, tzinfo=UTC),
            }
        )
    write_partition(
        pa.Table.from_pylist(rows, schema=github_prs.REPO_SCHEMA),
        RAW_DIR / "github_repos" / f"run_date={label}.parquet",
    )


def write_pypi(rng: random.Random) -> None:
    rows = []
    for repo, package in REPOS.items():
        if not package:
            continue
        for i in range(120):
            rows.append(
                {
                    "package": package,
                    "repo": repo,
                    "download_date": AS_OF - timedelta(days=120 - i),
                    "downloads": int(10_000 * (1 + i / 200) * rng.uniform(0.8, 1.2)),
                    "ingested_at": datetime(2026, 6, 30, 6, tzinfo=UTC),
                }
            )
    write_partition(
        pa.Table.from_pylist(rows, schema=PYPI_SCHEMA),
        RAW_DIR / "pypi_downloads" / "run_date=2026-06-30.parquet",
    )


def write_gharchive(salt: str, rng: random.Random) -> None:
    day = date(2026, 6, 29)
    events = []
    for i in range(400):
        repo = rng.choice([*REPOS, "other/repo"])
        events.append(
            {
                "id": str(10_000 + i),
                "type": rng.choice(["WatchEvent", "ForkEvent", "IssueCommentEvent", "PushEvent"]),
                "actor": {"login": rng.choice(PEOPLE + ["ci[bot]"])},
                "repo": {"name": repo},
                "created_at": f"2026-06-29T12:{i % 60:02d}:00Z",
                "payload": {"action": "started"},
            }
        )
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "2026-06-29-12.json.gz"
        with gzip.open(src, "wt", encoding="utf-8") as fh:
            for e in events:
                fh.write(json.dumps(e) + "\n")
        gharchive.land_hour(day, 12, list(REPOS), salt, source=src.as_posix())


LATE_REPO = "acme/late"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--late-repo",
        action="store_true",
        help=f"only add {LATE_REPO}: a backfill whose PRs are all older than the other "
        "repos' newest update, landed after a first build (incremental regression case)",
    )
    args = parser.parse_args()
    salt = get_salt()
    if args.late_repo:
        write_prs(salt, random.Random(7), [LATE_REPO], 150, "20260630T070000Z")
        write_repos([LATE_REPO], "2026-06-30-late")
        print(f"late repo {LATE_REPO} written to {RAW_DIR}")
        return
    rng = random.Random(42)
    write_prs(salt, rng, list(REPOS), 360, "20260630T060000Z")
    write_repos(list(REPOS), "2026-06-30")
    write_pypi(rng)
    write_gharchive(salt, rng)
    write_bot_keys(RAW_DIR, salt)
    print(f"fixture written to {RAW_DIR}")


if __name__ == "__main__":
    main()
