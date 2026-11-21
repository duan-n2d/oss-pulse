from datetime import UTC, datetime

import pyarrow as pa

from oss_pulse import github_prs
from oss_pulse.config import Repo
from oss_pulse.privacy import pseudonymize

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def user(login, typename="User"):
    return {"__typename": typename, "login": login}


def node(**overrides):
    base = {
        "number": 7,
        "createdAt": "2025-12-01T10:00:00Z",
        "updatedAt": "2025-12-02T10:00:00Z",
        "mergedAt": None,
        "closedAt": None,
        "isDraft": False,
        "state": "OPEN",
        "authorAssociation": "NONE",
        "additions": 3,
        "deletions": 1,
        "changedFiles": 1,
        "author": user("alice"),
        "mergedBy": None,
        "reviews": {
            "nodes": [
                {"submittedAt": None, "state": "PENDING", "author": user("bob")},
                {
                    "submittedAt": "2025-12-01T12:00:00Z",
                    "state": "COMMENTED",
                    "author": user("bob"),
                },
            ]
        },
        "comments": {
            "nodes": [
                {"createdAt": "2025-12-01T10:01:00Z", "author": user("codecov", "Bot")},
                {"createdAt": "2025-12-01T11:00:00Z", "author": None},
            ]
        },
    }
    base.update(overrides)
    return base


def test_record_pseudonymises_every_login(salt):
    rec = github_prs.pr_record("o/r", node(), salt, NOW)
    assert rec["author"] == {"key": pseudonymize("alice", salt), "is_bot": False}
    flat = str(rec)
    for login in ("alice", "bob", "codecov"):
        assert login not in flat


def test_pending_reviews_dropped_bots_flagged_ghosts_kept(salt):
    rec = github_prs.pr_record("o/r", node(), salt, NOW)
    assert len(rec["reviews"]) == 1  # the pending review has no timestamp
    assert rec["comments"][0]["actor"]["is_bot"] is True
    assert rec["comments"][1]["actor"] is None  # deleted ("ghost") account


def test_record_matches_landing_schema(salt):
    rec = github_prs.pr_record("o/r", node(), salt, NOW)
    assert pa.Table.from_pylist([rec], schema=github_prs.PR_SCHEMA).num_rows == 1


class FakeClient:
    """Two pages, newest first; the second page crosses the `since` boundary."""

    def __init__(self):
        self.calls = 0

    def query(self, query, variables):
        self.calls += 1
        pages = [
            [
                node(number=3, updatedAt="2025-12-20T00:00:00Z"),
                node(number=2, updatedAt="2025-12-10T00:00:00Z"),
            ],
            [
                node(number=1, updatedAt="2025-11-01T00:00:00Z"),
                node(number=0, updatedAt="2025-10-01T00:00:00Z"),
            ],
        ]
        return {
            "repository": {
                "pullRequests": {
                    "nodes": pages[self.calls - 1],
                    "pageInfo": {"hasNextPage": True, "endCursor": str(self.calls)},
                }
            }
        }


def test_paging_stops_at_since(salt):
    client = FakeClient()
    since = datetime(2025, 12, 1, tzinfo=UTC)
    records = github_prs.fetch_prs(client, Repo("o/r", None), since, salt, NOW)
    assert [r["number"] for r in records] == [3, 2]
    assert client.calls == 2


def test_land_prs_appends_one_file_per_run(tmp_path, monkeypatch, salt):
    monkeypatch.setattr(github_prs, "RAW_DIR", tmp_path)
    monkeypatch.setattr(
        github_prs, "fetch_prs", lambda *a, **k: [github_prs.pr_record("o/r", node(), salt, NOW)]
    )
    assert github_prs.land_prs(Repo("o/r", None), 365, salt, client=None) == 1
    files = list((tmp_path / "github_prs" / "repo=o__r").glob("run=*.parquet"))
    assert len(files) == 1
    assert github_prs.watermark("o/r") == datetime(2025, 12, 2, 10, tzinfo=UTC)
