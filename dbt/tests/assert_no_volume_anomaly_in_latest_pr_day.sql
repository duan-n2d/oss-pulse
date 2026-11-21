{{ config(severity='warn') }}
-- Warn (not fail) when the most recent day of PR activity looks anomalous for a repo:
-- usually an ingestion gap rather than a real change in behaviour.
select *
from {{ ref('obs_volume_anomalies') }}
where series = 'prs_opened'
  and is_anomaly
  and direction = 'drop'
  and obs_date = (select max(obs_date) from {{ ref('obs_volume_anomalies') }} where series = 'prs_opened')
