"""Land GH Archive events for the tracked repos, one Parquet partition per hour.

GH Archive publishes one gzipped JSON file per UTC hour. DuckDB streams the file over
HTTPS and keeps only the tracked repos, so nothing large touches disk. Each hour also
records the *global* event count of the file. That count is the coverage signal: it
is how OSS Pulse noticed that GH Archive volume fell by more than 90% in late 2026
(see docs/decisions.md), which a per-repo count alone would have hidden.

Layout (all overwritten on rerun, so a rerun of an hour is idempotent):
  raw/gharchive_events/date=YYYY-MM-DD/hour=HH.parquet   tracked-repo events
  raw/gharchive_volume/date=YYYY-MM-DD/hour=HH.parquet   one row: global file volume
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import duckdb
import pyarrow as pa

from .config import RAW_DIR
from .landing import write_partition
from .privacy import KNOWN_BOTS

log = logging.getLogger(__name__)

URL = "https://data.gharchive.org/{day}-{hour}.json.gz"
KEPT_TYPES = (
    "WatchEvent",
    "ForkEvent",
    "IssuesEvent",
    "IssueCommentEvent",
    "PullRequestEvent",
    "PullRequestReviewEvent",
    "PullRequestReviewCommentEvent",
    "ReleaseEvent",
    "PushEvent",
)


def hour_url(day: date, hour: int) -> str:
    return URL.format(day=day.isoformat(), hour=hour)  # GH Archive hours are not padded


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("set timezone = 'UTC'")
    return con


def land_hour(day: date, hour: int, repos: list[str], salt: str, source: str | None = None) -> int:
    """Land one GH Archive hour. `source` overrides the URL (used by tests)."""
    src = source or hour_url(day, hour)
    con = _connect()
    con.execute(
        f"""
        create temp table hour_events as
        select id, type, actor.login as login, repo.name as repo, created_at,
               payload ->> 'action' as action
        from read_json(?, format='newline_delimited', compression='gzip',
             columns={{'id': 'VARCHAR', 'type': 'VARCHAR', 'actor': 'STRUCT(login VARCHAR)',
                       'repo': 'STRUCT(name VARCHAR)', 'created_at': 'TIMESTAMPTZ',
                       'payload': 'JSON'}})
        """,
        [src],
    )
    volume = con.execute(
        """
        select count(*) as total_events,
               count(*) filter (where type = 'PushEvent') as push_events,
               count(distinct repo) as distinct_repos
        from hour_events
        """
    ).to_arrow_table()
    volume = volume.append_column(
        "hour_start", pa.array([datetime(day.year, day.month, day.day, hour, tzinfo=UTC)])
    ).append_column("ingested_at", pa.array([datetime.now(UTC).replace(microsecond=0)]))

    bots = sorted(KNOWN_BOTS)
    events = con.execute(
        f"""
        select id as event_id, type as event_type, action, repo, created_at,
               substr(sha256(? || ':' || lower(login)), 1, 16) as actor_key,
               (lower(login) like '%[bot]' or lower(login) like '%-bot'
                or lower(login) in (select unnest(?::varchar[]))) as actor_is_bot
        from hour_events
        where repo in (select unnest(?::varchar[]))
          and type in {KEPT_TYPES}
        """,
        [salt, bots, repos],
    ).to_arrow_table()

    part = f"date={day.isoformat()}/hour={hour:02d}.parquet"
    write_partition(events, RAW_DIR / "gharchive_events" / part)
    write_partition(volume, RAW_DIR / "gharchive_volume" / part)
    log.info(
        "gharchive %s %02d: %d tracked events of %d",
        day,
        hour,
        events.num_rows,
        volume["total_events"][0].as_py(),
    )
    return events.num_rows


def land_day(day: date, repos: list[str], salt: str, hours: range = range(24)) -> int:
    total = 0
    for hour in hours:
        total += land_hour(day, hour, repos, salt)
    return total
