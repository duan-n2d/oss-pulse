"""Command-line entry point: `oss-pulse <command>`."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime, timedelta

import duckdb

from . import gharchive, github_prs, pypi
from .config import load_config
from .privacy import get_salt

log = logging.getLogger("oss_pulse")


def cmd_ingest_github(args: argparse.Namespace) -> int:
    cfg = load_config()
    salt = get_salt()
    client = github_prs.GitHubClient(github_prs.github_token())
    repos = [r for r in cfg.repos if not args.repo or r.name in args.repo]
    total = 0
    for repo in repos:
        total += github_prs.land_prs(repo, cfg.window_days, salt, client)
    github_prs.land_repo_metadata(cfg.repos, client, datetime.now(UTC).date())
    log.info("github: %d PR versions landed", total)
    return 0


def _days(args: argparse.Namespace) -> list[date]:
    if args.date:
        return [date.fromisoformat(d) for d in args.date]
    return [datetime.now(UTC).date() - timedelta(days=1)]


def cmd_ingest_gharchive(args: argparse.Namespace) -> int:
    cfg = load_config()
    salt = get_salt()
    names = [r.name for r in cfg.repos]
    hours = [int(h) for h in args.hours.split(",")] if args.hours else list(range(24))
    missing = 0
    for day in _days(args):
        for hour in hours:
            try:
                gharchive.land_hour(day, hour, names, salt)
            except duckdb.HTTPException as exc:
                # A missing hour is recorded by its absence; the coverage monitor
                # reports hours_loaded < 24 for the day.
                log.warning("gharchive %s %02d unavailable: %s", day, hour, exc)
                missing += 1
    return 1 if missing and args.strict else 0


def cmd_ingest_pypi(args: argparse.Namespace) -> int:
    pypi.land_downloads(load_config().repos, datetime.now(UTC).date())
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from .warehouse import build

    return build(full_refresh=args.full_refresh, select=args.select)


def cmd_export(args: argparse.Namespace) -> int:
    from .export_site import export

    export()
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report import write_report

    write_report()
    return 0


def cmd_locate(args: argparse.Namespace) -> int:
    from .locate import locate

    print(locate(args.pr_url))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="oss-pulse")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest-github", help="land PRs (incremental) and repo metadata")
    p.add_argument("--repo", action="append", help="limit to a repo (repeatable)")
    p.set_defaults(func=cmd_ingest_github)

    p = sub.add_parser("ingest-gharchive", help="land GH Archive hours (default: yesterday)")
    p.add_argument("--date", action="append", help="YYYY-MM-DD (repeatable)")
    p.add_argument("--hours", help="comma-separated UTC hours, default all 24")
    p.add_argument("--strict", action="store_true", help="exit 1 if any hour is missing")
    p.set_defaults(func=cmd_ingest_gharchive)

    p = sub.add_parser("ingest-pypi", help="land daily PyPI downloads")
    p.set_defaults(func=cmd_ingest_pypi)

    p = sub.add_parser("build", help="restore state, dbt build, persist snapshot state")
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--select")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("export-site", help="export mart JSON for the static site")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("report", help="regenerate the README results block")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("locate", help="where does one PR sit in its repo's distribution")
    p.add_argument("pr_url", help="e.g. https://github.com/pola-rs/polars/pull/30893")
    p.set_defaults(func=cmd_locate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
