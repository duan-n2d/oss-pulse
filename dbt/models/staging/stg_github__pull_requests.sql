-- Latest landed version of each pull request. The landing zone is append-only
-- (one file per ingest run), so a PR can appear once per run that saw it change.
with versions as (
    select
        *,
        row_number() over (
            partition by repo, number
            order by updated_at desc, ingested_at desc
        ) as version_rank
    from {{ source('raw', 'github_prs') }}
)

select
    repo || '#' || number::varchar as pr_id,
    repo,
    number as pr_number,
    created_at,
    updated_at,
    merged_at,
    closed_at,
    is_draft,
    state as pr_state,
    author_association,
    additions,
    deletions,
    changed_files,
    author.key as author_key,
    coalesce(author.is_bot, false)
        or coalesce(author.key in (select bot_key from {{ ref('stg_bot_keys') }}), false) as author_is_bot,
    merged_by.key as merged_by_key,
    coalesce(merged_by.is_bot, false)
        or coalesce(merged_by.key in (select bot_key from {{ ref('stg_bot_keys') }}), false) as merged_by_is_bot,
    reviews,
    comments,
    ingested_at
from versions
where version_rank = 1
