import duckdb
import pytest

from oss_pulse import warehouse
from oss_pulse.config import load_config
from oss_pulse.locate import fmt_hours, parse_pr_url


def test_config_has_unique_repos_and_window():
    cfg = load_config()
    assert len(cfg.repos) >= 12
    assert len({r.name for r in cfg.repos}) == len(cfg.repos)
    assert cfg.window_days == 365


def test_snapshot_state_round_trips(tmp_path):
    db = tmp_path / "w.duckdb"
    state = tmp_path / "state"
    with duckdb.connect(str(db)) as con:
        con.execute("create schema snapshots")
        con.execute("create table snapshots.snap_github_repos as select 'a/b' as repo, 1 as v")
    assert warehouse.persist_state(db, state) == ["snap_github_repos"]

    fresh = tmp_path / "fresh.duckdb"
    assert warehouse.restore_state(fresh, state) == ["snap_github_repos"]
    assert warehouse.restore_state(fresh, state) == []  # already present: left alone
    with duckdb.connect(str(fresh)) as con:
        assert con.execute("select * from snapshots.snap_github_repos").fetchall() == [("a/b", 1)]


def test_parse_pr_url():
    assert parse_pr_url("https://github.com/pola-rs/polars/pull/30893") == ("pola-rs/polars", 30893)
    with pytest.raises(ValueError):
        parse_pr_url("https://github.com/pola-rs/polars/issues/1")


@pytest.mark.parametrize(
    ("hours", "text"),
    [(None, "no human response yet"), (0.5, "30 min"), (5, "5.0 h"), (72, "3.0 days")],
)
def test_fmt_hours(hours, text):
    assert fmt_hours(hours) == text
