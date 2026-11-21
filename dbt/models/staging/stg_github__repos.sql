-- Every metadata observation (one per repo per ingest run).
select
    repo,
    description,
    repo_created_at,
    is_archived,
    stars,
    forks,
    license,
    primary_language,
    default_branch,
    observed_at,
    observed_at::date as observed_date
from {{ source('raw', 'github_repos') }}
