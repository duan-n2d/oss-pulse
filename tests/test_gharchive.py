import gzip
import json
from datetime import date

import duckdb

from oss_pulse import gharchive
from oss_pulse.privacy import pseudonymize


def write_hour(path, events):
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


def event(i, repo, type_="WatchEvent", login="alice"):
    return {
        "id": str(i),
        "type": type_,
        "actor": {"login": login},
        "repo": {"name": repo},
        "created_at": "2026-06-29T12:00:00Z",
        "payload": {"action": "started"},
    }


def read(path):
    glob = (path / "**" / "*.parquet").as_posix()
    return duckdb.execute(f"select * from read_parquet('{glob}', hive_partitioning=false)")


def test_land_hour_filters_hashes_and_is_idempotent(tmp_path, monkeypatch, salt):
    monkeypatch.setattr(gharchive, "RAW_DIR", tmp_path)
    src = tmp_path / "hour.json.gz"
    write_hour(
        src,
        [
            event(1, "a/tracked"),
            event(2, "a/tracked", "ForkEvent", "dependabot[bot]"),
            event(3, "z/other"),
            event(4, "a/tracked", "GollumEvent"),  # not a kept event type
        ],
    )
    for _ in range(2):  # rerunning the same hour must not duplicate rows
        n = gharchive.land_hour(date(2026, 6, 29), 12, ["a/tracked"], salt, source=src.as_posix())
    assert n == 2

    rows = sorted(read(tmp_path / "gharchive_events").fetchall(), key=lambda r: r[0])
    assert len(rows) == 2
    cols = [d[0] for d in read(tmp_path / "gharchive_events").description]
    first = dict(zip(cols, rows[0], strict=True))
    second = dict(zip(cols, rows[1], strict=True))
    assert first["actor_key"] == pseudonymize("alice", salt)
    assert first["actor_is_bot"] is False
    assert second["actor_is_bot"] is True

    volume = read(tmp_path / "gharchive_volume").fetchall()
    assert len(volume) == 1
    assert volume[0][:3] == (4, 0, 2)  # total events, push events, distinct repos


def test_hour_url_is_not_zero_padded():
    assert gharchive.hour_url(date(2026, 1, 2), 5).endswith("2026-01-02-5.json.gz")
