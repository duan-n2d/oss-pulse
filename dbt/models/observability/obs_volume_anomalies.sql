-- Volume monitor: compare each observation of a series with its own trailing history.
-- Series:
--   prs_opened         PRs opened per repo per day (GitHub API)
--   pypi_downloads     downloads per package per day (pypistats)
--   gharchive_volume   global GH Archive events per loaded hour, per day observed
-- An observation is anomalous when it is more than 3 standard deviations from the
-- trailing mean, or below 20% of it (a collapse that a z-score can understate when
-- the history is noisy). Trailing = the previous 28 observations of that series,
-- needing at least 8 of them.
{% set z_threshold = 3 %}
{% set collapse_ratio = 0.2 %}

with series as (
    select 'prs_opened' as series, repo as entity, activity_date as obs_date,
           prs_opened::double as value
    from {{ ref('fct_repo_activity_daily') }}
    where activity_date >= {{ window_start() }}
      and activity_date < {{ as_of_date() }}  -- today is still a partial day

    union all

    select 'pypi_downloads', package, download_date, downloads::double
    from {{ ref('fct_package_downloads_daily') }}

    union all

    select 'gharchive_volume', 'all public events (per hour)', volume_date,
           avg(total_events)::double
    from {{ ref('stg_gharchive__hour_volume') }}
    group by volume_date
),

scored as (
    select
        *,
        avg(value) over w as trailing_mean,
        stddev_samp(value) over w as trailing_std,
        count(value) over w as trailing_n
    from series
    window w as (
        partition by series, entity order by obs_date
        rows between 28 preceding and 1 preceding
    )
)

select
    series::varchar as series,
    entity::varchar as entity,
    obs_date::date as obs_date,
    value::double as value,
    trailing_mean::double as trailing_mean,
    trailing_std::double as trailing_std,
    trailing_n::bigint as trailing_n,
    ((value - trailing_mean) / nullif(trailing_std, 0))::double as z_score,
    (value / nullif(trailing_mean, 0))::double as ratio_to_trailing,
    (trailing_n >= 8 and (
        abs((value - trailing_mean) / nullif(trailing_std, 0)) > {{ z_threshold }}
        or value / nullif(trailing_mean, 0) < {{ collapse_ratio }}
    ))::boolean as is_anomaly,
    (case
        when trailing_n < 8 then null
        when value >= trailing_mean then 'spike'
        else 'drop'
    end)::varchar as direction
from scored
