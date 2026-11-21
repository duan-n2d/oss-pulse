{{ config(contract={'enforced': true}) }}

-- 101 quantiles of time to first response per repo (answered PRs only) and the share
-- never answered. Lets the dashboard place a single PR within its repo without
-- exporting PR-level rows.
with prs as (
    select repo, hours_to_first_response as h
    from {{ ref('fct_pull_request') }}
    where created_at >= {{ window_start() }}
      and created_at < {{ as_of_date() }} + interval 1 day
      and not author_is_bot
      and not is_draft
)

select
    repo::varchar as repo,
    count(*)::bigint as prs,
    avg((h is null)::int)::double as share_unanswered,
    (quantile_cont(h, [{% for i in range(101) %}{{ i / 100 }}{% if not loop.last %}, {% endif %}{% endfor %}])
        filter (where h is not null))::double[] as quantiles
from prs
group by repo
