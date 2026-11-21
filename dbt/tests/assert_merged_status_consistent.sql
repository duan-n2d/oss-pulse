-- status, merged_at and hours_to_merge must agree.
select pr_id
from {{ ref('fct_pull_request') }}
where (status = 'merged') <> (merged_at is not null)
   or (merged_at is not null and hours_to_merge is null)
