# Governance

GitHub activity is public, but it is still personal data: a login identifies a
person, and a year of their review and merge timestamps is a behavioural profile.
OSS Pulse treats it that way.

## Pseudonymisation at the edge

* Every login (PR author, reviewer, commenter, merger, GH Archive actor) is replaced
  by `substr(sha256(salt || ':' || lower(login)), 1, 16)` **before anything is
  written** to the landing zone. Raw logins never touch disk, the public `data`
  branch, the warehouse or the site.
* The salt is a secret (`OSS_PULSE_SALT`, at least 16 characters; the pipeline
  refuses to run without it). Without it, keys cannot be reversed by hashing a list of
  known logins. Locally it lives in the git-ignored `.salt`; in Actions it is a
  repository secret. The local and Actions values must match or keys from different
  runs will not join.
* Bot status is decided from the login before hashing and kept as a flag, so bots
  can be excluded without keeping their names.
* The same hash is computed in Python (PR data) and in DuckDB (GH Archive); a unit
  test asserts the two agree.

## What pseudonymisation does not do

It is not anonymisation. A PR number plus repo is public and leads straight back to
its author on GitHub, so `fct_pull_request` rows are re-identifiable by anyone with
internet access. Consequences:

* Under GDPR (Recital 26) and Vietnam's personal data protection rules
  (Decree 13/2023/ND-CP, and the Law on Personal Data Protection effective
  1 January 2026), pseudonymised data remains personal data.
* The **public site exports aggregates only** (per-repo KPIs, histograms, quantiles,
  weekly counts). No PR-level rows and no contributor keys are published.
* The `data` branch does contain PR-level rows with pseudonymised keys. They hold
  nothing that is not already public on GitHub, minus the logins.

## Purpose and minimisation

* Purpose: aggregate review and merge behaviour of projects, not of people. There is
  no per-person leaderboard and no model that scores individuals.
* Only the fields needed for the KPIs are landed: no PR titles, bodies, comment text,
  emails, names or avatars.
* `oss-pulse locate` and the site's "Locate a PR" work from a PR URL, not a login,
  so they need neither the salt nor any lookup of the person.

## Controls in the pipeline

| Control | Where |
|---|---|
| Logins hashed before landing | `src/oss_pulse/privacy.py`, `github_prs.pr_record`, `gharchive.land_hour` |
| Pipeline refuses to run without a strong salt | `privacy.get_salt` (tested) |
| Keys must look like hashes, never like logins | dbt test `is_pseudonymised_key` on `dim_contributor` and every key column of `fct_pull_request` |
| Only aggregates leave the warehouse | `src/oss_pulse/export_site.py` |
| Contracts on every mart | `dbt/models/marts/_marts.yml` (`contract: enforced`) |
| Freshness and volume monitoring | `obs_source_freshness`, `obs_volume_anomalies`, `obs_gharchive_coverage`, `dbt source freshness` |

## Erasure

A person who asks to be removed can be honoured by hashing their login with the
salt and deleting matching keys from the landing zone, then rebuilding; the warehouse
and site are derived and rebuild from it. (Not automated: there has been no request
and the data is public at source.)

## Licences

GH Archive data is CC-BY-4.0. GitHub API data is used under the GitHub Terms of
Service for public repository metadata. pypistats.org data is derived from the public
PyPI BigQuery dataset.
