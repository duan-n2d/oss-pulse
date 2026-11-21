select distinct on (event_id)
    event_id,
    event_type,
    action,
    repo,
    created_at,
    created_at::date as event_date,
    actor_key,
    coalesce(actor_is_bot, false) as actor_is_bot
from {{ source('raw', 'gharchive_events') }}
order by event_id
