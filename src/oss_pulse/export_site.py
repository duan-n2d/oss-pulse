"""Export mart tables as JSON for the static dashboard (site/data/*.json).

Only aggregates leave the warehouse: no PR-level rows and no contributor keys are
exported, so the public site cannot be joined back to individuals.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from .config import ROOT, WAREHOUSE

SITE_DATA = ROOT / "site" / "data"

QUERIES: dict[str, str] = {
    "scorecard": "select * from marts.mart_repo_scorecard order by prs_opened desc",
    "distribution": """
        select * from marts.mart_response_time_distribution order by repo, bucket_order
    """,
    "latency_by_type": """
        select * from marts.mart_latency_by_contributor_type order by repo, contributor_type
    """,
    "response_quantiles": "select * from marts.mart_response_quantiles order by repo",
    "weekly_activity": """
        select repo, date_trunc('week', activity_date)::date as week,
               sum(prs_opened) as prs_opened, sum(prs_merged) as prs_merged,
               sum(prs_closed_unmerged) as prs_closed_unmerged
        from marts.fct_repo_activity_daily
        where activity_date >= (select max(activity_date) - 364 from marts.fct_repo_activity_daily)
        group by all order by repo, week
    """,
    "weekly_downloads": """
        select package, repo, date_trunc('week', download_date)::date as week,
               sum(downloads) as downloads, count(*) as days
        from marts.fct_package_downloads_daily
        group by all having count(*) = 7 order by package, week
    """,
    "freshness": "select * from observability.obs_source_freshness order by source_name",
    "anomalies": """
        select * from observability.obs_volume_anomalies
        where is_anomaly
          and obs_date >= (select max(obs_date) - 60 from observability.obs_volume_anomalies)
        order by obs_date desc, series, entity
    """,
    "gharchive_coverage": "select * from observability.obs_gharchive_coverage order by volume_date",
    "meta": """
        select
            (select max(date_day) from marts.dim_date) as as_of,
            (select count(*) from marts.dim_repo) as repos,
            (select sum(prs_opened) from marts.mart_repo_scorecard) as prs_in_window,
            (select count(*) from marts.fct_pull_request) as prs_landed,
            (select count(*) from marts.dim_contributor where not is_bot) as human_contributors,
            (select count(*) from observability.obs_gharchive_coverage) as gharchive_days_sampled
    """,
}


def _clean(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def query_records(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [{c: _clean(v) for c, v in zip(cols, row, strict=True)} for row in cur.fetchall()]


def export(warehouse: Path = WAREHOUSE, out_dir: Path = SITE_DATA) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    with duckdb.connect(str(warehouse), read_only=True) as con:
        con.execute("set timezone = 'UTC'")
        for name, sql in QUERIES.items():
            records = query_records(con, sql)
            payload = records[0] if name == "meta" else records
            if name == "meta":
                payload["generated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
            (out_dir / f"{name}.json").write_text(
                json.dumps(payload, separators=(",", ":")), encoding="utf-8"
            )
            counts[name] = len(records)
    return counts
