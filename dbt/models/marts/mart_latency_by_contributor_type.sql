{{ config(contract={'enforced': true}) }}

-- Do newcomers wait longer than maintainers for a first response and a merge?
select
    repo::varchar as repo,
    contributor_type::varchar as contributor_type,
    count(*)::bigint as prs_opened,
    median(hours_to_first_response)::double as median_hours_to_first_response,
    median(hours_to_merge)::double as median_hours_to_merge,
    (count(*) filter (where status = 'merged')
        / nullif(count(*) filter (where status in ('merged', 'closed')), 0))::double
        as merge_rate
from {{ ref('fct_pull_request') }}
where created_at >= {{ window_start() }}
  and created_at < {{ as_of_date() }} + interval 1 day
  and not author_is_bot
  and not is_draft
group by all
