"""Regenerate the RESULTS block of README.md from the warehouse.

Every number in that block comes from this function; nothing is typed by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from .config import ROOT, WAREHOUSE

README = ROOT / "README.md"
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def _hours(h: float | None) -> str:
    if h is None:
        return "n/a"
    return f"{h:.1f} h" if h < 48 else f"{h / 24:.1f} d"


def _int(v: int | None) -> str:
    return "n/a" if v is None else f"{v:,}"


def render(warehouse: Path = WAREHOUSE) -> str:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        con.execute("set timezone = 'UTC'")
        as_of, prs_window, humans = con.execute(
            """
            select (select max(date_day) from marts.dim_date),
                   (select sum(prs_opened) from marts.mart_repo_scorecard),
                   (select count(*) from marts.dim_contributor where not is_bot)
            """
        ).fetchone()
        rows = con.execute(
            """
            select repo, prs_opened, merge_rate, median_hours_to_first_response,
                   share_unanswered_7d, median_hours_to_merge, merger_bus_factor,
                   downloads_last_30d, merges_tracked_on_github
            from marts.mart_repo_scorecard order by median_hours_to_first_response
            """
        ).fetchall()
        newcomer = con.execute(
            """
            select
              median(median_hours_to_first_response) filter (where contributor_type = 'newcomer'),
              median(median_hours_to_first_response) filter (where contributor_type = 'maintainer'),
              median(merge_rate) filter (where contributor_type = 'newcomer'),
              median(merge_rate) filter (where contributor_type = 'maintainer')
            from marts.mart_latency_by_contributor_type
            """
        ).fetchone()
        cov = con.execute(
            """
            select
              median(avg_events_per_hour) filter (where volume_date < date '2026-01-01'),
              median(avg_events_per_hour) filter (where volume_date >= current_date - 14),
              min(volume_date) filter (where coverage_ratio < 0.2),
              count(*)
            from observability.obs_gharchive_coverage
            """
        ).fetchone()
        anomalies = con.execute(
            "select count(*) from observability.obs_volume_anomalies where is_anomaly"
        ).fetchone()[0]

    lines = [
        f"As of **{as_of}**: {len(rows)} repositories, **{_int(prs_window)} human-authored, "
        f"non-draft PRs** opened in the last 365 days, {_int(humans)} pseudonymised human "
        "contributors. Sorted by median time to first human response.",
        "",
        "| Repository | PRs | Merge rate | Median first response | Unanswered after 7 d "
        "| Median time to merge | Merger bus factor | PyPI downloads, 30 d |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    untracked = False
    for repo, prs, mr, fr, un, tm, bf, dl, tracked in rows:
        mark = "" if tracked else " †"
        untracked = untracked or not tracked
        lines.append(
            f"| {repo}{mark} | {_int(prs)} | {_pct(mr)} | {_hours(fr)} | {_pct(un)} "
            f"| {_hours(tm)} | {_int(bf)} | {_int(dl)} |"
        )
    if untracked:
        lines += [
            "",
            "† Merges happen outside GitHub's merge button (GitHub records accepted PRs as "
            "closed), so merge metrics are not measurable from GitHub.",
        ]
    n_fr, m_fr, n_mr, m_mr = newcomer
    lines += [
        "",
        f"* Across repos (median of repo medians), newcomers wait **{_hours(n_fr)}** for a "
        f"first response versus **{_hours(m_fr)}** for maintainers, and their PRs merge "
        f"**{_pct(n_mr)}** of the time versus **{_pct(m_mr)}**.",
    ]
    before, recent, first_drop, days = cov
    if before and recent:
        lines.append(
            f"* GH Archive coverage: a median hour held **{_int(round(before))}** public events "
            f"before 2026 and **{_int(round(recent))}** in the last 14 days "
            f"({recent / before:.0%}); the first sampled day below 20% of the baseline was "
            f"**{first_drop}** ({days} days sampled). Star/fork/comment counts from GH Archive "
            "are therefore shown with their coverage, not as totals."
        )
    lines.append(f"* Volume monitor: {anomalies} anomalous observations flagged across all series.")
    return "\n".join(lines)


def write_report(readme: Path = README, warehouse: Path = WAREHOUSE) -> None:
    text = readme.read_text(encoding="utf-8")
    block = f"{START}\n{render(warehouse)}\n{END}"
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    readme.write_text(new, encoding="utf-8")
