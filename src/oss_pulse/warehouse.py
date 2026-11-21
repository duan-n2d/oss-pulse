"""Run dbt against the local DuckDB warehouse, carrying snapshot state across runs.

The warehouse file itself is disposable: every run can rebuild it from the landed
Parquet. The one thing that cannot be rebuilt is SCD2 history, so the snapshot table
is exported to `data/state/` after a successful build and restored into a fresh
warehouse before the next one. In GitHub Actions `data/` lives on the `data` branch.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import duckdb

from .config import DATA_DIR, ROOT, STATE_DIR, WAREHOUSE

log = logging.getLogger(__name__)

DBT_DIR = ROOT / "dbt"
SNAPSHOTS = ("snap_github_repos",)


def dbt_env() -> dict[str, str]:
    env = dict(os.environ)
    env["OSS_PULSE_DATA_DIR"] = DATA_DIR.resolve().as_posix()
    env["OSS_PULSE_WAREHOUSE"] = WAREHOUSE.resolve().as_posix()
    env.setdefault("DBT_PROFILES_DIR", DBT_DIR.as_posix())
    return env


def restore_state(warehouse: Path = WAREHOUSE, state_dir: Path = STATE_DIR) -> list[str]:
    """Load persisted snapshot tables into the warehouse if it does not have them."""
    restored = []
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(warehouse)) as con:
        con.execute("create schema if not exists snapshots")
        for name in SNAPSHOTS:
            path = state_dir / f"{name}.parquet"
            exists = con.execute(
                "select count(*) from information_schema.tables "
                "where table_schema = 'snapshots' and table_name = ?",
                [name],
            ).fetchone()[0]
            if path.exists() and not exists:
                con.execute(
                    f"create table snapshots.{name} as select * from read_parquet(?)",
                    [path.as_posix()],
                )
                restored.append(name)
    return restored


def persist_state(warehouse: Path = WAREHOUSE, state_dir: Path = STATE_DIR) -> list[str]:
    state_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    with duckdb.connect(str(warehouse), read_only=True) as con:
        for name in SNAPSHOTS:
            path = state_dir / f"{name}.parquet"
            tmp = path.with_suffix(".parquet.tmp")
            con.execute(
                f"copy snapshots.{name} to '{tmp.as_posix()}' (format parquet, compression zstd)"
            )
            tmp.replace(path)
            saved.append(name)
    return saved


def run_dbt(*args: str) -> int:
    exe = Path(sys.executable).with_name("dbt.exe" if os.name == "nt" else "dbt")
    cmd = [str(exe), *args, "--project-dir", DBT_DIR.as_posix()]
    log.info("running: dbt %s", " ".join(args))
    return subprocess.run(cmd, env=dbt_env(), cwd=DBT_DIR).returncode


def build(full_refresh: bool = False, select: str | None = None) -> int:
    restored = restore_state()
    if restored:
        log.info("restored snapshot state: %s", ", ".join(restored))
    # Freshness is reported, not enforced: a stale source should show up on the
    # dashboard rather than stop the rest of the pipeline.
    run_dbt("source", "freshness")
    args = ["build"]
    if full_refresh:
        args.append("--full-refresh")
    if select:
        args += ["--select", select]
    code = run_dbt(*args)
    if code == 0:
        log.info("persisted snapshot state: %s", ", ".join(persist_state()))
    return code
