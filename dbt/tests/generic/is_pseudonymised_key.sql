{# Governance guard: a contributor key must look like the 16-hex-char salted hash
   written by the ingest step, never like a raw GitHub login. #}
{% test is_pseudonymised_key(model, column_name) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and not regexp_full_match({{ column_name }}, '[0-9a-f]{16}')
{% endtest %}
