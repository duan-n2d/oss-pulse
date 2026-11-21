-- Does this repo merge through GitHub's merge button? Some projects (Apache Spark)
-- merge with a committer script that pushes the commit and closes the PR, so GitHub
-- records almost every accepted PR as "closed", never "merged". For those repos merge
-- rate, time to merge and the bus factors are not measurable from GitHub and are
-- reported as null rather than as a misleading 0% merge rate.
{% set min_merged_share = 0.05 %}
{% set min_resolved = 50 %}

select
    repo,
    count(*) filter (where status = 'merged') as prs_merged_on_github,
    count(*) filter (where status in ('merged', 'closed')) as prs_resolved,
    (count(*) filter (where status = 'merged')
        / nullif(count(*) filter (where status in ('merged', 'closed')), 0)) as github_merged_share,
    not (
        count(*) filter (where status in ('merged', 'closed')) >= {{ min_resolved }}
        and count(*) filter (where status = 'merged')
            < {{ min_merged_share }} * count(*) filter (where status in ('merged', 'closed'))
    ) as merges_tracked_on_github
from {{ ref('fct_pull_request') }}
where not author_is_bot
group by repo
