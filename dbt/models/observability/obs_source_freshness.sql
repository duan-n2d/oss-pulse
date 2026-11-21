-- How stale is each source? Mirrors `dbt source freshness` (which is also run in the
-- pipeline) but lands as a table so the dashboard can show it.
{% set sources = [
    ('github_prs', 'ingested_at', 'stg_github__pull_requests', 48, 168),
    ('github_repos', 'observed_at', 'stg_github__repos', 48, 168),
    ('gharchive_events', 'created_at', 'stg_gharchive__events', 48, 168),
    ('gharchive_volume', 'hour_start', 'stg_gharchive__hour_volume', 48, 168),
    ('pypi_downloads', 'ingested_at', 'stg_pypi__downloads', 48, 168),
] %}

with latest as (
    {% for name, col, model, warn_h, error_h in sources %}
    select
        '{{ name }}' as source_name,
        max({{ col }}) as latest_loaded_at,
        count(*) as row_count,
        {{ warn_h }} as warn_after_hours,
        {{ error_h }} as error_after_hours
    from {{ ref(model) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select
    source_name::varchar as source_name,
    latest_loaded_at::timestamptz as latest_loaded_at,
    row_count::bigint as row_count,
    (date_diff('minute', latest_loaded_at, now()) / 60.0)::double as lag_hours,
    (case
        when latest_loaded_at is null then 'error'
        when date_diff('minute', latest_loaded_at, now()) / 60.0 > error_after_hours then 'error'
        when date_diff('minute', latest_loaded_at, now()) / 60.0 > warn_after_hours then 'warn'
        else 'pass'
    end)::varchar as status,
    now()::timestamptz as checked_at
from latest
