-- A PR cannot be merged, closed or first answered before it was opened.
select pr_id
from {{ ref('fct_pull_request') }}
where merged_at < created_at
   or closed_at < created_at
   or first_response_at < created_at
