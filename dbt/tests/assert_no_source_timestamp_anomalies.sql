{{ config(severity='warn') }}
-- Surface (do not fail on) PRs whose source timestamps are inconsistent.
select pr_id, created_at, merged_at, closed_at
from {{ ref('fct_pull_request') }}
where has_source_timestamp_anomaly
