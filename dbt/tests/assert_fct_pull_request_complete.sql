-- Every landed PR must reach the fact table. Guards the incremental logic: a repo
-- whose backfill lands late, with older updated_at values than other repos, must
-- not be skipped (a global watermark once did exactly that).
select s.pr_id
from {{ ref('stg_github__pull_requests') }} as s
left join {{ ref('fct_pull_request') }} as f using (pr_id)
where f.pr_id is null
