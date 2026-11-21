{{ config(contract={'enforced': true}) }}

-- Histogram of time to first response per repo, for the dashboard.
{% set buckets = [
    (1, '< 1h'), (4, '1-4h'), (24, '4-24h'), (72, '1-3d'),
    (168, '3-7d'), (720, '7-30d')
] %}

with prs as (
    select repo, hours_to_first_response as h
    from {{ ref('fct_pull_request') }}
    where created_at >= {{ window_start() }}
      and created_at < {{ as_of_date() }} + interval 1 day
      and not author_is_bot
      and not is_draft
),

bucketed as (
    select
        repo,
        case
            when h is null then 'no response yet'
            {% for upper, label in buckets %}
            when h < {{ upper }} then '{{ label }}'
            {% endfor %}
            else '> 30d'
        end as bucket,
        case
            when h is null then {{ buckets | length + 2 }}
            {% for upper, label in buckets %}
            when h < {{ upper }} then {{ loop.index }}
            {% endfor %}
            else {{ buckets | length + 1 }}
        end as bucket_order
    from prs
)

select
    repo::varchar as repo,
    bucket::varchar as bucket,
    bucket_order::integer as bucket_order,
    count(*)::bigint as prs,
    (count(*) / sum(count(*)) over (partition by repo))::double as share
from bucketed
group by repo, bucket, bucket_order
