"""Land pull requests and repository metadata from the GitHub GraphQL API.

Pull requests are paged newest-`updatedAt` first and paging stops at the watermark
(the newest `updatedAt` already landed) or at the start of the analysis window,
whichever is later. Each run appends one Parquet file per repo under
`raw/github_prs/repo=<owner__name>/run=<timestamp>.parquet`; staging keeps the latest
version of each PR, so reruns and overlapping runs are harmless.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import requests

from .config import RAW_DIR, Repo
from .landing import write_partition
from .privacy import is_bot, pseudonymize

log = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.github.com/graphql"
PAGE_SIZE = 50

PR_QUERY = """
query($owner: String!, $name: String!, $after: String, $first: Int!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    pullRequests(first: $first, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number createdAt updatedAt mergedAt closedAt isDraft state authorAssociation
        additions deletions changedFiles
        author { __typename login }
        mergedBy { __typename login }
        reviews(first: 10) { nodes { submittedAt state author { __typename login } } }
        comments(first: 10) { nodes { createdAt author { __typename login } } }
      }
    }
  }
}
"""

REPO_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner description createdAt isArchived stargazerCount forkCount
    licenseInfo { spdxId } primaryLanguage { name } defaultBranchRef { name }
  }
}
"""

ACTOR = pa.struct([("key", pa.string()), ("is_bot", pa.bool_())])
EVENT = pa.struct([("at", pa.timestamp("us", tz="UTC")), ("actor", ACTOR), ("state", pa.string())])

PR_SCHEMA = pa.schema(
    [
        ("repo", pa.string()),
        ("number", pa.int64()),
        ("created_at", pa.timestamp("us", tz="UTC")),
        ("updated_at", pa.timestamp("us", tz="UTC")),
        ("merged_at", pa.timestamp("us", tz="UTC")),
        ("closed_at", pa.timestamp("us", tz="UTC")),
        ("is_draft", pa.bool_()),
        ("state", pa.string()),
        ("author_association", pa.string()),
        ("additions", pa.int64()),
        ("deletions", pa.int64()),
        ("changed_files", pa.int64()),
        ("author", ACTOR),
        ("merged_by", ACTOR),
        ("reviews", pa.list_(EVENT)),
        ("comments", pa.list_(EVENT)),
        ("ingested_at", pa.timestamp("us", tz="UTC")),
    ]
)

REPO_SCHEMA = pa.schema(
    [
        ("repo", pa.string()),
        ("description", pa.string()),
        ("repo_created_at", pa.timestamp("us", tz="UTC")),
        ("is_archived", pa.bool_()),
        ("stars", pa.int64()),
        ("forks", pa.int64()),
        ("license", pa.string()),
        ("primary_language", pa.string()),
        ("default_branch", pa.string()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
    ]
)


def github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        return subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("set GITHUB_TOKEN or log in with `gh auth login`") from exc


def _ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHubClient:
    def __init__(self, token: str, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"bearer {token}", "User-Agent": "oss-pulse"})

    def query(self, query: str, variables: dict, retries: int = 6) -> dict:
        delay = 5.0
        for attempt in range(retries):
            resp = self.session.post(
                GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=60
            )
            if resp.status_code in (502, 503, 504) or (
                resp.status_code == 403 and "rate limit" in resp.text.lower()
            ):
                retry_after = float(resp.headers.get("Retry-After", delay))
                log.warning("GitHub %s, retrying in %.0fs", resp.status_code, retry_after)
                time.sleep(retry_after)
                delay = min(delay * 2, 300)
                continue
            resp.raise_for_status()
            body = resp.json()
            if body.get("errors"):
                # Large pages occasionally time out server-side; retry those.
                messages = "; ".join(e.get("message", "") for e in body["errors"])
                if "timeout" in messages.lower() or "something went wrong" in messages.lower():
                    log.warning("GraphQL error %r, retry %d", messages, attempt + 1)
                    time.sleep(delay)
                    delay = min(delay * 2, 300)
                    continue
                raise RuntimeError(f"GraphQL errors: {messages}")
            self._respect_rate_limit(body["data"].get("rateLimit"))
            return body["data"]
        raise RuntimeError(f"GitHub API failed after {retries} attempts")

    @staticmethod
    def _respect_rate_limit(rate: dict | None) -> None:
        if rate and rate["remaining"] < 50:
            reset = _ts(rate["resetAt"])
            wait = max(0.0, (reset - datetime.now(UTC)).total_seconds()) + 5
            log.warning("rate limit nearly exhausted, sleeping %.0fs", wait)
            time.sleep(wait)


def _actor(node: dict | None, salt: str) -> dict | None:
    if node is None:  # deleted ("ghost") account
        return None
    login, typename = node.get("login"), node.get("__typename")
    return {"key": pseudonymize(login, salt), "is_bot": is_bot(login, typename)}


def pr_record(repo: str, node: dict, salt: str, ingested_at: datetime) -> dict:
    """Flatten one GraphQL PR node; logins are pseudonymised here, before landing."""
    return {
        "repo": repo,
        "number": node["number"],
        "created_at": _ts(node["createdAt"]),
        "updated_at": _ts(node["updatedAt"]),
        "merged_at": _ts(node["mergedAt"]),
        "closed_at": _ts(node["closedAt"]),
        "is_draft": node["isDraft"],
        "state": node["state"],
        "author_association": node["authorAssociation"],
        "additions": node["additions"],
        "deletions": node["deletions"],
        "changed_files": node["changedFiles"],
        "author": _actor(node["author"], salt),
        "merged_by": _actor(node["mergedBy"], salt),
        "reviews": [
            {"at": _ts(r["submittedAt"]), "actor": _actor(r["author"], salt), "state": r["state"]}
            for r in node["reviews"]["nodes"]
            if r["submittedAt"] is not None  # pending reviews have no timestamp
        ],
        "comments": [
            {"at": _ts(c["createdAt"]), "actor": _actor(c["author"], salt), "state": None}
            for c in node["comments"]["nodes"]
        ],
        "ingested_at": ingested_at,
    }


def repo_partition_dir(repo: str) -> Path:
    return RAW_DIR / "github_prs" / f"repo={repo.replace('/', '__')}"


def watermark(repo: str) -> datetime | None:
    """Newest updated_at already landed for this repo, or None."""
    files = list(repo_partition_dir(repo).glob("*.parquet"))
    if not files:
        return None
    glob = (repo_partition_dir(repo) / "*.parquet").as_posix()
    row = duckdb.execute(
        f"select max(updated_at) from read_parquet('{glob}', hive_partitioning = false)"
    ).fetchone()
    return row[0]


def fetch_prs(
    client: GitHubClient, repo: Repo, since: datetime, salt: str, ingested_at: datetime
) -> list[dict]:
    """Page PRs newest-updated first until updatedAt < since."""
    records: list[dict] = []
    after = None
    while True:
        data = client.query(
            PR_QUERY,
            {"owner": repo.owner, "name": repo.short, "after": after, "first": PAGE_SIZE},
        )
        page = data["repository"]["pullRequests"]
        done = False
        for node in page["nodes"]:
            if _ts(node["updatedAt"]) < since:
                done = True
                break
            records.append(pr_record(repo.name, node, salt, ingested_at))
        if done or not page["pageInfo"]["hasNextPage"]:
            return records
        after = page["pageInfo"]["endCursor"]


def land_prs(repo: Repo, window_days: int, salt: str, client: GitHubClient) -> int:
    now = datetime.now(UTC).replace(microsecond=0)
    window_start = now - timedelta(days=window_days)
    mark = watermark(repo.name)
    # Re-read one day before the watermark: PRs updated in the same second as the
    # previous run's last page must not be missed.
    since = max(window_start, mark - timedelta(days=1)) if mark else window_start
    records = fetch_prs(client, repo, since, salt, now)
    # One file per run (not per day): a second run on the same day must not replace
    # the first run's batch. Staging keeps the newest version of each PR.
    if records:
        path = repo_partition_dir(repo.name) / f"run={now.strftime('%Y%m%dT%H%M%SZ')}.parquet"
        write_partition(pa.Table.from_pylist(records, schema=PR_SCHEMA), path)
    log.info("%s: %d PRs updated since %s", repo.name, len(records), since.isoformat())
    return len(records)


def land_repo_metadata(repos: list[Repo], client: GitHubClient, run_date: date) -> int:
    now = datetime.now(UTC).replace(microsecond=0)
    rows = []
    for repo in repos:
        r = client.query(REPO_QUERY, {"owner": repo.owner, "name": repo.short})["repository"]
        rows.append(
            {
                "repo": repo.name,
                "description": r["description"],
                "repo_created_at": _ts(r["createdAt"]),
                "is_archived": r["isArchived"],
                "stars": r["stargazerCount"],
                "forks": r["forkCount"],
                "license": (r["licenseInfo"] or {}).get("spdxId"),
                "primary_language": (r["primaryLanguage"] or {}).get("name"),
                "default_branch": (r["defaultBranchRef"] or {}).get("name"),
                "observed_at": now,
            }
        )
    path = RAW_DIR / "github_repos" / f"run_date={run_date.isoformat()}.parquet"
    write_partition(pa.Table.from_pylist(rows, schema=REPO_SCHEMA), path)
    return len(rows)
