{{
    config(
        materialized='incremental',
        unique_key='pr_id',
        incremental_strategy='delete+insert',
        on_schema_change='fail',
        contract={'enforced': true},
    )
}}

-- Grain: one pull request. Incremental on updated_at: a PR is rebuilt whenever it
-- changes (merged, reviewed, closed), with a one-day overlap for late landings.
-- The watermark is per repo. A single global max(updated_at) would skip a repo
-- whose backfill lands after another repo's newer increment, because the
-- backfilled PRs all carry older updated_at values.
with prs as (
    select s.*
    from {{ ref('stg_github__pull_requests') }} as s
    {% if is_incremental() %}
    left join (
        select repo, max(updated_at) as watermark from {{ this }} group by repo
    ) as w using (repo)
    where w.watermark is null
       or s.updated_at > w.watermark - interval 1 day
    {% endif %}
),

responses as (
    select * from {{ ref('int_pr_first_response') }}
),

-- Position of each PR among its author's PRs in the repo, over all landed data
-- (not just this increment). Newcomer status is derived from this sequence, not
-- from authorAssociation: GitHub evaluates the association at query time, so a
-- newcomer whose PR has since been merged reads as CONTRIBUTOR, which would leave
-- only unmerged PRs labelled as newcomers (survivorship bias).
author_sequence as (
    select
        pr_id,
        row_number() over (
            partition by repo, author_key order by created_at, pr_number
        ) as author_pr_seq
    from {{ ref('stg_github__pull_requests') }}
    where author_key is not null
)

select
    p.pr_id::varchar as pr_id,
    p.repo::varchar as repo,
    p.pr_number::bigint as pr_number,
    p.author_key::varchar as author_key,
    p.author_is_bot::boolean as author_is_bot,
    p.author_association::varchar as author_association,
    a.author_pr_seq::bigint as author_pr_seq,
    (case
        when p.author_association in ('OWNER', 'MEMBER', 'COLLABORATOR') then 'maintainer'
        when p.author_key is null then 'unknown'
        when a.author_pr_seq = 1 then 'newcomer'
        else 'returning_contributor'
    end)::varchar as contributor_type,
    p.created_at::timestamptz as created_at,
    p.created_at::date as created_date,
    p.updated_at::timestamptz as updated_at,
    p.merged_at::timestamptz as merged_at,
    p.closed_at::timestamptz as closed_at,
    (case
        when p.merged_at is not null then 'merged'
        when p.closed_at is not null then 'closed'
        else 'open'
    end)::varchar as status,
    p.is_draft::boolean as is_draft,
    p.merged_by_key::varchar as merged_by_key,
    p.additions::bigint as additions,
    p.deletions::bigint as deletions,
    p.changed_files::bigint as changed_files,
    (case
        when p.additions + p.deletions < 10 then 'XS'
        when p.additions + p.deletions < 50 then 'S'
        when p.additions + p.deletions < 250 then 'M'
        when p.additions + p.deletions < 1000 then 'L'
        else 'XL'
    end)::varchar as size_bucket,
    r.first_response_at::timestamptz as first_response_at,
    r.first_review_at::timestamptz as first_review_at,
    r.first_responder_key::varchar as first_responder_key,
    r.distinct_responders::bigint as distinct_responders,
    (date_diff('second', p.created_at, r.first_response_at) / 3600.0)::double
        as hours_to_first_response,
    (date_diff('second', p.created_at, r.first_review_at) / 3600.0)::double
        as hours_to_first_review,
    -- GitHub occasionally reports a PR merged or closed before it was opened (e.g. an
    -- Airflow backport opened after its commit was already on the base branch). Keep
    -- the source timestamps, flag the row, and leave the duration null.
    (p.merged_at < p.created_at or p.closed_at < p.created_at)::boolean
        as has_source_timestamp_anomaly,
    (case when p.merged_at >= p.created_at
        then date_diff('second', p.created_at, p.merged_at) / 3600.0
    end)::double as hours_to_merge
from prs as p
left join responses as r using (pr_id)
left join author_sequence as a using (pr_id)
