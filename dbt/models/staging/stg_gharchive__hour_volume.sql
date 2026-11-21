select distinct on (hour_start)
    hour_start,
    hour_start::date as volume_date,
    total_events,
    push_events,
    distinct_repos,
    ingested_at
from {{ source('raw', 'gharchive_volume') }}
order by hour_start, ingested_at desc
