-- One row per review or top-level comment on a PR (the first 10 of each kind, which
-- is enough to find the first response; see docs/decisions.md).
with prs as (
    select pr_id, reviews, comments from {{ ref('stg_github__pull_requests') }}
),

reviews as (
    select pr_id, 'review' as response_type, unnest(reviews, recursive := true)
    from prs
),

comments as (
    select pr_id, 'comment' as response_type, unnest(comments, recursive := true)
    from prs
)

select pr_id, response_type, "at" as responded_at, key as actor_key,
       coalesce(is_bot, false) as actor_is_bot, state as review_state
from reviews
union all
select pr_id, response_type, "at", key, coalesce(is_bot, false), state
from comments
