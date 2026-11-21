# Runbook

## First-time setup of the GitHub repository

1. **Salt secret.** Create `OSS_PULSE_SALT` under Settings → Secrets and variables →
   Actions with the *same* value as the local `.salt` used for the backfill.
2. **Pages.** Settings → Pages → Source: *GitHub Actions*.
3. **Seed the data branch** from the local backfill (the default `GITHUB_TOKEN` has a
   lower GraphQL budget, so the 365-day backfill is done locally with a personal
   token, after which the daily job only fetches increments):

   ```bash
   GIT_AUTHOR_NAME="..." GIT_AUTHOR_EMAIL="...@users.noreply.github.com" \
     bash scripts/publish_data_branch.sh data origin
   ```

4. Run the `daily` workflow once from the Actions tab (`workflow_dispatch`).

## Daily job fails

| Step | Likely cause | Action |
|---|---|---|
| Ingest GitHub | `MissingSaltError` | the `OSS_PULSE_SALT` secret is missing or shorter than 16 characters |
| Ingest GitHub | rate limit / 502s | the client backs off and retries; rerun the job |
| Ingest GH Archive | an hour returns 404 | logged as a warning and skipped; the day shows fewer than 24 hours loaded |
| dbt build | contract or test failure | read the failing test; contracts fail on purpose when a column type changes |
| Publish data branch | push rejected | check `permissions: contents: write` on the workflow |

## Rerunning

Every step is safe to rerun. GitHub PRs append a new batch and staging keeps the
latest version of each PR; GH Archive hours overwrite their own file; pypistats files
are per run date. To backfill GH Archive days:

```bash
oss-pulse ingest-gharchive --date 2026-11-01 --date 2026-11-02
```

## Rotating the salt

Changing the salt changes every key, so it requires re-landing: delete
`data/raw/github_prs` and `data/raw/gharchive_events`, set the new salt locally and as
the secret, run the full backfill, and republish the data branch. `data/state` holds
repository attributes only (no contributor keys) and can be kept.
