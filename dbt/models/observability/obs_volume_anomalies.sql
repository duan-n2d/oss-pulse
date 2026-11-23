-- Volume monitor: compare each observation of a series with its own trailing history.
-- Series:
--   prs_opened         PRs opened per repo per day (GitHub API)
--   pypi_downloads     downloads per package per day (pypistats)
--   gharchive_volume   global GH Archive events per loaded hour, per day observed
-- Each observation is compared with the same weekday in the previous 8 weeks of its
-- series (at least 4 needed): PR and download volumes have a strong weekly cycle,
-- and a first version that used the previous 28 days flagged 129 ordinary weekends
-- as drops. With so few points the standard deviation is small, so a z-score alone
-- flagged hundreds of trivial moves (a 4% dip included). Anomalous therefore means:
--   statistically AND practically significant: |z| > 3, at least +/-50% from the
--   mean, and at least 5 units away from it; or
--   a collapse: below 20% of a mean of at least 5.
{% set z_threshold = 3 %}
{% set collapse_ratio = 0.2 %}
{% set min_mean_for_collapse = 5 %}
{% set lookback_weeks = 8 %}
{% set min_relative_change = 0.5 %}
{% set min_absolute_change = 5 %}
{% set min_history = 4 %}

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
        partition by series, entity, isodow(obs_date) order by obs_date
        rows between {{ lookback_weeks }} preceding and 1 preceding
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
    (trailing_n >= {{ min_history }} and (
        (abs((value - trailing_mean) / nullif(trailing_std, 0)) > {{ z_threshold }}
            and abs(value / nullif(trailing_mean, 0) - 1) >= {{ min_relative_change }}
            and abs(value - trailing_mean) >= {{ min_absolute_change }})
        or (trailing_mean >= {{ min_mean_for_collapse }}
            and value / nullif(trailing_mean, 0) < {{ collapse_ratio }})
    ))::boolean as is_anomaly,
    (case
        when trailing_n < {{ min_history }} then null
        when value >= trailing_mean then 'spike'
        else 'drop'
    end)::varchar as direction
from scored
