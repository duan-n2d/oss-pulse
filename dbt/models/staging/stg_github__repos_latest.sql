-- Latest observation per repo: the input to the SCD2 snapshot.
select * exclude (rn)
from (
    select *, row_number() over (partition by repo order by observed_at desc) as rn
    from {{ ref('stg_github__repos') }}
)
where rn = 1
