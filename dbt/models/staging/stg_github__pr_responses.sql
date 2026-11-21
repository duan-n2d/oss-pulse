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
),

responses as (
    select pr_id, response_type, "at" as responded_at, key as actor_key, is_bot,
           state as review_state
    from reviews
    union all
    select pr_id, response_type, "at", key, is_bot, state
    from comments
)

select
    pr_id,
    response_type,
    responded_at,
    actor_key,
    coalesce(is_bot, false)
        or coalesce(actor_key in (select bot_key from {{ ref('stg_bot_keys') }}), false) as actor_is_bot,
    review_state
from responses
