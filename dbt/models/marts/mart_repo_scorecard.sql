{{ config(contract={'enforced': true}) }}

-- One row per repo: review responsiveness, merge outcomes, concentration and
-- adoption over the analysis window. Population: human-authored, non-draft PRs
-- created inside the window.
{% set unanswered = var('unanswered_after_hours') %}

with prs as (
    select *
    from {{ ref('fct_pull_request') }}
    where created_at >= {{ window_start() }}
      and created_at < {{ as_of_date() }} + interval 1 day
      and not author_is_bot
      and not is_draft
),

-- Only PRs old enough to have had the full grace period count for "unanswered".
matured as (
    select *
    from prs
    where created_at <= {{ as_of_date() }} - interval {{ unanswered }} hours
),

flow as (
    select
        repo,
        count(*) as prs_opened,
        count(*) filter (where status = 'merged') as prs_merged,
        count(*) filter (where status = 'closed') as prs_closed_unmerged,
        count(*) filter (where status = 'open') as prs_still_open,
        count(distinct author_key) as distinct_authors,
        median(hours_to_first_response) as median_hours_to_first_response,
        quantile_cont(hours_to_first_response, 0.9) as p90_hours_to_first_response,
        median(hours_to_merge) as median_hours_to_merge,
        avg(coalesce(hours_to_first_response <= 24, false)::int) as share_responded_within_24h
    from prs
    group by repo
),

unanswered as (
    select
        repo,
        avg((first_response_at is null
             or hours_to_first_response > {{ unanswered }})::int) as share_unanswered_7d
    from matured
    group by repo
),

-- Smallest number of people accounting for >= 50% of merged PRs, by author and by
-- the maintainer who pressed merge.
author_shares as (
    select repo, author_key as person, count(*) as n
    from prs where status = 'merged' and author_key is not null group by all
),

merger_shares as (
    select repo, merged_by_key as person, count(*) as n
    from prs where status = 'merged' and merged_by_key is not null group by all
),

{% for kind in ['author', 'merger'] %}
{{ kind }}_ranked as (
    select
        repo,
        row_number() over (partition by repo order by n desc, person) as rnk,
        sum(n) over (partition by repo order by n desc, person rows unbounded preceding)
            / sum(n) over (partition by repo) as cum_share
    from {{ kind }}_shares
),

{{ kind }}_factor as (
    select repo, min(rnk) as factor from {{ kind }}_ranked where cum_share >= 0.5 group by repo
),
{% endfor %}

-- Newcomers whose first PR in the window is at least 90 days old: did they open
-- another PR in the same repo within 90 days?
first_prs as (
    select repo, author_key, min(created_at) as first_at
    from prs where author_key is not null group by all
),

newcomer_first as (
    select f.repo, f.author_key, f.first_at
    from first_prs as f
    inner join prs as p
        on p.repo = f.repo and p.author_key = f.author_key and p.created_at = f.first_at
    where p.contributor_type = 'newcomer'
      and f.first_at <= {{ as_of_date() }} - interval 90 days
),

newcomer_return as (
    select
        n.repo,
        count(distinct n.author_key) as newcomers_eligible,
        count(distinct p2.author_key) as newcomers_returned
    from newcomer_first as n
    left join prs as p2
        on p2.repo = n.repo and p2.author_key = n.author_key
       and p2.created_at > n.first_at
       and p2.created_at <= n.first_at + interval 90 days
    group by n.repo
),

latest_download as (
    select max(download_date) as d from {{ ref('fct_package_downloads_daily') }}
),

downloads as (
    select
        f.repo,
        sum(f.downloads) filter (where f.download_date > l.d - 30) as downloads_last_30d,
        sum(f.downloads) filter (
            where f.download_date <= l.d - 30 and f.download_date > l.d - 60
        ) as downloads_prev_30d
    from {{ ref('fct_package_downloads_daily') }} as f
    cross join latest_download as l
    group by f.repo
)

select
    r.repo::varchar as repo,
    r.pypi_package::varchar as pypi_package,
    r.stars::bigint as stars,
    coalesce(f.prs_opened, 0)::bigint as prs_opened,
    coalesce(f.prs_merged, 0)::bigint as prs_merged,
    coalesce(f.prs_closed_unmerged, 0)::bigint as prs_closed_unmerged,
    coalesce(f.prs_still_open, 0)::bigint as prs_still_open,
    (f.prs_merged / nullif(f.prs_merged + f.prs_closed_unmerged, 0))::double as merge_rate,
    f.distinct_authors::bigint as distinct_authors,
    f.median_hours_to_first_response::double as median_hours_to_first_response,
    f.p90_hours_to_first_response::double as p90_hours_to_first_response,
    f.share_responded_within_24h::double as share_responded_within_24h,
    u.share_unanswered_7d::double as share_unanswered_7d,
    f.median_hours_to_merge::double as median_hours_to_merge,
    af.factor::bigint as author_bus_factor,
    mf.factor::bigint as merger_bus_factor,
    nr.newcomers_eligible::bigint as newcomers_eligible,
    (nr.newcomers_returned / nullif(nr.newcomers_eligible, 0))::double
        as newcomer_return_rate_90d,
    d.downloads_last_30d::bigint as downloads_last_30d,
    (d.downloads_last_30d / nullif(d.downloads_prev_30d, 0) - 1)::double
        as downloads_growth_30d
from {{ ref('dim_repo') }} as r
left join flow as f using (repo)
left join unanswered as u using (repo)
left join author_factor as af using (repo)
left join merger_factor as mf using (repo)
left join newcomer_return as nr using (repo)
left join downloads as d using (repo)
