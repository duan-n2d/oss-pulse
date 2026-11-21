{{ config(contract={'enforced': true}) }}

-- Grain: one pseudonymised contributor (PR author, reviewer or merger) seen in the
-- landed data. There is deliberately no login column; see docs/governance.md.
with authors as (
    select author_key as contributor_key, author_is_bot as is_bot, repo, created_at as seen_at,
           'author' as role, status
    from {{ ref('fct_pull_request') }}
    where author_key is not null
),

responders as (
    select r.actor_key, r.actor_is_bot, p.repo, r.responded_at, 'responder', null
    from {{ ref('stg_github__pr_responses') }} as r
    inner join {{ ref('stg_github__pull_requests') }} as p using (pr_id)
    where r.actor_key is not null
),

mergers as (
    select merged_by_key, false, repo, merged_at, 'merger', null
    from {{ ref('fct_pull_request') }}
    where merged_by_key is not null
),

activity as (
    select * from authors
    union all select * from responders
    union all select * from mergers
)

select
    contributor_key::varchar as contributor_key,
    bool_or(is_bot)::boolean as is_bot,
    min(seen_at)::timestamptz as first_seen_at,
    max(seen_at)::timestamptz as last_seen_at,
    count(distinct repo)::bigint as repos_active_in,
    count(*) filter (where role = 'author')::bigint as prs_authored,
    count(*) filter (where role = 'author' and status = 'merged')::bigint as prs_merged,
    count(*) filter (where role = 'responder')::bigint as responses_given,
    count(*) filter (where role = 'merger')::bigint as prs_merged_as_maintainer
from activity
group by contributor_key
