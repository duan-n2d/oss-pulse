{{ config(contract={'enforced': true}) }}

select
    d::date as date_day,
    year(d)::integer as year,
    quarter(d)::integer as quarter,
    month(d)::integer as month,
    strftime(d, '%Y-%m') as year_month,
    date_trunc('week', d)::date as week_start,
    isodow(d)::integer as iso_day_of_week,
    (isodow(d) >= 6) as is_weekend
from generate_series(
    ({{ window_start() }})::date - interval '{{ var("window_days") }} days',
    {{ as_of_date() }},
    interval 1 day
) as t(d)
