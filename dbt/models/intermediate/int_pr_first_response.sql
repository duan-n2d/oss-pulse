-- First human response to each PR from someone other than its author.
-- "Response" = a submitted review or a top-level comment; bots (CI, coverage,
-- labelers) and the author's own comments do not count.
with prs as (
    select pr_id, author_key, created_at
    from {{ ref('stg_github__pull_requests') }}
),

human_responses as (
    select r.pr_id, r.response_type, r.responded_at, r.actor_key
    from {{ ref('stg_github__pr_responses') }} as r
    inner join prs as p using (pr_id)
    where not r.actor_is_bot
      and r.actor_key is not null
      and r.actor_key is distinct from p.author_key
      and r.responded_at >= p.created_at
)

select
    p.pr_id,
    min(h.responded_at) as first_response_at,
    min(h.responded_at) filter (where h.response_type = 'review') as first_review_at,
    arg_min(h.actor_key, h.responded_at) as first_responder_key,
    count(distinct h.actor_key) as distinct_responders
from prs as p
left join human_responses as h using (pr_id)
group by p.pr_id
