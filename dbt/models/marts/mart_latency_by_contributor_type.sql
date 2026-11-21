{{ config(contract={'enforced': true}) }}

-- Do newcomers wait longer than maintainers for a first response and a merge?
select
    p.repo::varchar as repo,
    p.contributor_type::varchar as contributor_type,
    count(*)::bigint as prs_opened,
    median(p.hours_to_first_response)::double as median_hours_to_first_response,
    (case when bool_and(mt.merges_tracked_on_github) then median(p.hours_to_merge) end)::double
        as median_hours_to_merge,
    (case when bool_and(mt.merges_tracked_on_github) then
        count(*) filter (where p.status = 'merged')
        / nullif(count(*) filter (where p.status in ('merged', 'closed')), 0)
    end)::double as merge_rate
from {{ ref('fct_pull_request') }} as p
inner join {{ ref('int_repo_merge_tracking') }} as mt using (repo)
where p.created_at >= {{ window_start() }}
  and p.created_at < {{ as_of_date() }} + interval 1 day
  and not p.author_is_bot
  and not p.is_draft
group by p.repo, p.contributor_type
