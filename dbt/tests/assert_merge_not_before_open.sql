-- Nothing can be answered before it was opened, and a merged/closed-before-opened PR
-- must carry has_source_timestamp_anomaly (and no negative duration).
select pr_id
from {{ ref('fct_pull_request') }}
where first_response_at < created_at
   or ((merged_at < created_at or closed_at < created_at) and not has_source_timestamp_anomaly)
   or hours_to_merge < 0
