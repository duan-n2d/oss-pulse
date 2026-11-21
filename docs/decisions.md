# Design decisions

## Sources

**GitHub GraphQL API for pull requests (authoritative).** PRs are paged newest
`updatedAt` first and paging stops at the landed watermark minus one day (or at the
start of the 365-day window on the first run). One query returns the PR, its first
10 reviews and first 10 top-level comments, which is enough to find the first human
response: bots and the author's own comments are the usual early noise, and the first
non-author human almost always appears within the first ten of each. Review-thread
(inline) comments are not fetched; a maintainer who only leaves inline comments
without submitting a review is therefore missed. On repos that review mostly through
plain comments (Apache Spark) this is covered by the top-level comments.

**GH Archive for stars, forks and comments, with a coverage monitor.** GH Archive was
meant to be the activity source. Sampling one hour a week for a year showed that a
median hour held about 155k public events through July 2026, became unstable from
August, and has held only a few thousand events since mid-October 2026, with
`PushEvent` absent from most hours. A per-repo count alone would read this as the
projects going quiet. So:

* every landed hour also records the global event count of the file,
  `obs_gharchive_coverage` compares it with the pre-2026 median hour, and
  `obs_volume_anomalies` flags the collapse;
* PR activity in `fct_repo_activity_daily` comes from the GitHub API, not GH Archive;
* GH Archive columns carry `gharchive_hours_loaded` and are treated as a sample.

The README's results block reports the measured coverage numbers.

**pypistats.org for adoption.** Daily downloads without mirrors for the last ~180
days. The API re-serves its whole window on each call; staging keeps the newest
observation of each package-day. Two config choices follow from the package mapping:
Iceberg is tracked as `apache/iceberg-python` (PyPI `pyiceberg`) and Delta as
`delta-io/delta-rs` (PyPI `deltalake`), because the JVM repositories do not ship the
Python packages. `apache/arrow-js` ships to npm, so it has no download series.

## Landing zone and idempotency

* GitHub PRs: one Parquet file per repo per run (`run=<UTC timestamp>`), append-only.
  A second run on the same day cannot overwrite the first (an early version named
  files by date and did exactly that). Staging keeps the latest version of each PR.
* GH Archive: one file per UTC hour, overwritten on rerun, so reruns are idempotent.
  A missing hour is skipped and shows up as `gharchive_hours_loaded < 24`.
* pypistats: one file per run date; staging dedups package-days.

## Persistence between Actions runs: an orphan `data` branch

Options considered: Actions cache (evicted after 7 days of no use, so not durable),
release assets (fine, but awkward to update many small files), an external bucket
(needs an account), and a git branch. The `data` branch is force-pushed as a single
commit on each run, so git history does not grow; the landing zone itself is the
history. The DuckDB warehouse is never stored: it is rebuilt from `raw/` each run
(seconds at this size). The one thing that cannot be rebuilt is SCD2 history, so the
snapshot table is exported to `state/snap_github_repos.parquet` after each build and
restored into the fresh warehouse before the next.

## Modelling

* Star schema: `fct_pull_request` (grain: PR), `fct_repo_activity_daily` (repo x day),
  `fct_package_downloads_daily` (package x day), `dim_repo`, `dim_contributor`,
  `dim_date`. KPI marts sit on top for the dashboard.
* `fct_pull_request` is incremental on `updated_at` with a one-day overlap and
  `delete+insert` on `pr_id`. The daily facts recompute a trailing lookback (3 and 7
  days) to absorb late merges and late GH Archive hours. In Actions the warehouse is
  rebuilt each run, so the first build is always full; locally the incremental path
  runs (CI runs both).
* Contracts are enforced on every mart; a contract change fails the build instead of
  silently changing a column type the dashboard reads.
* **Newcomer status is derived from the data, not from `authorAssociation`.** The
  first version used the association, and the first real build showed newcomers
  merging 9% of the time against 92% for maintainers. The cause was survivorship
  bias, not reality: GitHub evaluates the association at query time, so a newcomer
  whose PR was merged now reads as `CONTRIBUTOR`, leaving only the unmerged PRs
  labelled as newcomers. Now `maintainer` still comes from the association
  (OWNER/MEMBER/COLLABORATOR), and `newcomer` means the author's first PR in that
  repo within the landed data (`author_pr_seq = 1`). With that definition, newcomer
  PRs merge 58% of the time (median across repos). The remaining bias is that
  someone who contributed before the landed window and then paused looks new.
* **Bots typed as users.** `flinkbot` (CI report on every Flink PR within minutes)
  and `HuggingFaceDocBuilderDev` were counted as human responders and made Flink
  look like it answered in 6 minutes. Bot detection now also uses a maintained list,
  `privacy.KNOWN_BOTS`. Its hashed keys are rewritten to `raw/bot_keys` on every
  ingest and ORed into every `is_bot` flag in staging, so adding a bot reclassifies
  data landed earlier without re-ingesting. The list was checked by looking for
  first responders with very high counts and minute-level median latency.
* **Merges outside GitHub.** Apache Spark merges with a committer script that pushes
  the commit and closes the PR, so GitHub records about 0.01% of Spark's resolved PRs
  as merged. `int_repo_merge_tracking` marks a repo as not tracking merges when fewer
  than 5% of at least 50 resolved PRs are merged. Merge rate, time to merge and bus
  factors are then null instead of a misleading 0%.
* **Source timestamp anomalies are flagged, not failed.** GitHub reports at least one
  Airflow backport as merged 53 minutes before it was opened (the commit was already
  on the base branch). `has_source_timestamp_anomaly` keeps the source values, the
  duration is null, and a warn-level test lists such rows.
* Star and fork counts change daily, so they are facts (latest value on `dim_repo`),
  not SCD2 attributes; the snapshot tracks description, archive status, licence,
  language and default branch.

## KPI definitions

* **First human response**: earliest submitted review or top-level comment by someone
  other than the author, not a bot, at or after PR creation.
* **Merge rate**: merged / (merged + closed unmerged), PRs opened in the window.
  Still-open PRs are excluded rather than counted as failures.
* **Unanswered after 7 days**: among PRs at least 7 days old, share with no human
  response within 168 hours.
* **Bus factor** (author / merger): fewest people accounting for at least half of
  merged PRs, by author or by who pressed merge. A low merger bus factor means a few
  maintainers gate everything.
* **Newcomer return rate**: newcomers whose first PR in the window is at least 90 days
  old and who opened another PR in the same repo within 90 days.

Populations exclude bot-authored and draft PRs.

## Volume monitor

Each observation is compared with its own previous 28 observations (at least 8
required): anomalous when |z| > 3, or when it falls below 20% of the trailing mean and
that mean is at least 5. The minimum mean stops sparse series, where a zero day is
normal, from alarming on every quiet day. Today's partial day is excluded.

## Dashboard

A static page (Observable Plot over exported JSON) instead of Evidence.dev: no build
toolchain to keep working in CI, and the JSON export is an explicit, reviewable
boundary of what is published. Only aggregates are exported. "Locate a PR" calls the
GitHub REST API from the visitor's browser and compares the result with 101 exported
quantiles, so the page never needs PR-level rows.
