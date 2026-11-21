{{
    config(
        materialized='incremental',
        unique_key=['package', 'download_date'],
        incremental_strategy='delete+insert',
        on_schema_change='fail',
        contract={'enforced': true},
    )
}}

-- Grain: package x day (PyPI, mirrors excluded). The rolling average is computed over
-- the full staged series and only the recent rows are rewritten on incremental runs.
with series as (
    select
        package,
        repo,
        download_date,
        downloads,
        avg(downloads) over (
            partition by package order by download_date
            rows between 6 preceding and current row
        ) as downloads_7d_avg,
        count(*) over (
            partition by package order by download_date
            rows between 6 preceding and current row
        ) as days_in_avg
    from {{ ref('stg_pypi__downloads') }}
)

select
    package::varchar as package,
    repo::varchar as repo,
    download_date::date as download_date,
    downloads::bigint as downloads,
    (case when days_in_avg = 7 then downloads_7d_avg end)::double as downloads_7d_avg
from series
{% if is_incremental() %}
where download_date >= (select max(download_date) - 7 from {{ this }})
{% endif %}
