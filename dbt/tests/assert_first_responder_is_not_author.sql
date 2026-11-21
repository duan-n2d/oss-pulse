-- The first response must come from someone other than the PR author.
select pr_id
from {{ ref('fct_pull_request') }}
where first_responder_key is not null
  and first_responder_key = author_key
