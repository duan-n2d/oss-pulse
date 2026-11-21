{{ config(contract={'enforced': true}) }}

-- Current version of each repo from the SCD2 snapshot, plus its PyPI package and the
-- latest observed popularity counts.
with current_attrs as (
    select * from {{ ref('snap_github_repos') }} where dbt_valid_to is null
),

latest_counts as (
    select repo, stars, forks, observed_at
    from {{ ref('stg_github__repos_latest') }}
),

packages as (
    select distinct repo, package from {{ ref('stg_pypi__downloads') }}
)

select
    c.repo::varchar as repo,
    split_part(c.repo, '/', 1)::varchar as owner,
    c.description::varchar as description,
    c.primary_language::varchar as primary_language,
    c.license::varchar as license,
    c.default_branch::varchar as default_branch,
    c.is_archived::boolean as is_archived,
    c.repo_created_at::timestamptz as repo_created_at,
    p.package::varchar as pypi_package,
    l.stars::bigint as stars,
    l.forks::bigint as forks,
    l.observed_at::timestamptz as counts_observed_at,
    c.dbt_valid_from::timestamptz as attributes_valid_from
from current_attrs as c
left join latest_counts as l using (repo)
left join packages as p using (repo)
