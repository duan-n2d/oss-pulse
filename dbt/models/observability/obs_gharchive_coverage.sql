-- GH Archive coverage per observed day: how many hours were loaded and how many
-- events an hour held, relative to the median hour before 2026. Explains why star,
-- fork and comment counts from GH Archive are shown with a coverage caveat.
with hours as (
    select * from {{ ref('stg_gharchive__hour_volume') }}
),

baseline as (
    select median(total_events) as median_events_per_hour
    from hours
    where hour_start < timestamptz '2026-01-01 00:00:00+00'
)

select
    h.volume_date::date as volume_date,
    count(*)::bigint as hours_loaded,
    avg(h.total_events)::double as avg_events_per_hour,
    avg(h.push_events)::double as avg_push_events_per_hour,
    b.median_events_per_hour::double as baseline_events_per_hour,
    (avg(h.total_events) / nullif(b.median_events_per_hour, 0))::double as coverage_ratio
from hours as h
cross join baseline as b
group by h.volume_date, b.median_events_per_hour
