"""Place one pull request in its repo's time-to-first-response distribution.

Works from a PR URL, not a login, so it needs no access to the salt and nothing
about the author is looked up.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from .config import WAREHOUSE

PR_URL = re.compile(r"github\.com/([^/]+/[^/]+)/pull/(\d+)")


def parse_pr_url(url: str) -> tuple[str, int]:
    m = PR_URL.search(url)
    if not m:
        raise ValueError(f"not a GitHub PR URL: {url}")
    return m.group(1), int(m.group(2))


def fmt_hours(h: float | None) -> str:
    if h is None:
        return "no human response yet"
    if h < 1:
        return f"{h * 60:.0f} min"
    if h < 48:
        return f"{h:.1f} h"
    return f"{h / 24:.1f} days"


def locate(url: str, warehouse: Path = WAREHOUSE) -> str:
    repo, number = parse_pr_url(url)
    with duckdb.connect(str(warehouse), read_only=True) as con:
        pr = con.execute(
            """
            select status, created_at, hours_to_first_response, hours_to_merge, contributor_type
            from marts.fct_pull_request where repo = ? and pr_number = ?
            """,
            [repo, number],
        ).fetchone()
        if pr is None:
            return f"{repo}#{number} is not in the landed data (outside the window or untracked)."
        status, created_at, hours, merge_hours, ctype = pr
        q = con.execute(
            "select prs, share_unanswered, quantiles from marts.mart_response_quantiles "
            "where repo = ?",
            [repo],
        ).fetchone()
        median = con.execute(
            "select median_hours_to_first_response from marts.mart_repo_scorecard where repo = ?",
            [repo],
        ).fetchone()[0]
    lines = [
        f"{repo}#{number}: {status}, opened {created_at:%Y-%m-%d}, author type {ctype}",
        f"  first human response: {fmt_hours(hours)} (repo median {fmt_hours(median)})",
    ]
    if hours is not None and q is not None:
        prs, share_unanswered, quantiles = q
        faster = sum(1 for v in quantiles if v < hours) / len(quantiles)
        answered_share = 1 - share_unanswered
        rank = faster * answered_share
        lines.append(
            f"  waited longer than ~{rank:.0%} of {prs} PRs in the window "
            f"({share_unanswered:.0%} of them never got a response)"
        )
    if merge_hours is not None:
        lines.append(f"  merged after {fmt_hours(merge_hours)}")
    return "\n".join(lines)
