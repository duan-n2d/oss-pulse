{{
    config(
        materialized='incremental',
        unique_key=['repo', 'activity_date'],
        incremental_strategy='delete+insert',
        on_schema_change='fail',
        contract={'enforced': true},
    )
}}

-- Grain: repo x day. PR counts come from the GitHub API (complete). Stars, forks and
-- comments come from GH Archive, whose coverage varies, so every day carries the
-- number of GH Archive hours loaded and the global volume of those hours.
-- Incremental: the last 3 days are recomputed on each run (late merges, late hours).
{% set lookback_days = 3 %}

with days as (
    select r.repo, d.date_day as activity_date
    from {{ ref('dim_repo') }} as r
    cross join {{ ref('dim_date') }} as d
    {% if is_incremental() %}
    where d.date_day >= (select max(activity_date) - {{ lookback_days }} from {{ this }})
    {% endif %}
),

prs as (
    select * from {{ ref('fct_pull_request') }} where not author_is_bot
),

opened as (
    select repo, created_date as activity_date, count(*) as n from prs group by all
),

merged as (
    select repo, merged_at::date as activity_date, count(*) as n
    from prs where merged_at is not null group by all
),

closed as (
    select repo, closed_at::date as activity_date, count(*) as n
    from prs where status = 'closed' group by all
),

responded as (
    select repo, first_response_at::date as activity_date, count(*) as n
    from prs where first_response_at is not null group by all
),

gha as (
    select
        repo,
        event_date as activity_date,
        count(*) filter (where event_type = 'WatchEvent') as stars,
        count(*) filter (where event_type = 'ForkEvent') as forks,
        count(*) filter (where event_type = 'IssueCommentEvent' and not actor_is_bot)
            as issue_comments
    from {{ ref('stg_gharchive__events') }}
    group by all
),

coverage as (
    select volume_date as activity_date,
           count(*) as hours_loaded,
           sum(total_events) as global_events
    from {{ ref('stg_gharchive__hour_volume') }}
    group by all
)

select
    d.repo::varchar as repo,
    d.activity_date::date as activity_date,
    coalesce(o.n, 0)::bigint as prs_opened,
    coalesce(m.n, 0)::bigint as prs_merged,
    coalesce(c.n, 0)::bigint as prs_closed_unmerged,
    coalesce(r.n, 0)::bigint as prs_first_responded,
    (case when cv.hours_loaded is not null then coalesce(g.stars, 0) end)::bigint
        as gharchive_stars,
    (case when cv.hours_loaded is not null then coalesce(g.forks, 0) end)::bigint
        as gharchive_forks,
    (case when cv.hours_loaded is not null then coalesce(g.issue_comments, 0) end)::bigint
        as gharchive_issue_comments,
    coalesce(cv.hours_loaded, 0)::bigint as gharchive_hours_loaded,
    cv.global_events::bigint as gharchive_global_events
from days as d
left join opened as o using (repo, activity_date)
left join merged as m using (repo, activity_date)
left join closed as c using (repo, activity_date)
left join responded as r using (repo, activity_date)
left join gha as g using (repo, activity_date)
left join coverage as cv using (activity_date)
