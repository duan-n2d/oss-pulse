{# The analysis date. Pinned by `--vars "as_of: 2026-11-20"` for reproducible runs
   and CI fixtures; defaults to today (UTC). #}
{% macro as_of_date() -%}
  {%- if var('as_of') -%} date '{{ var("as_of") }}' {%- else -%} current_date {%- endif -%}
{%- endmacro %}

{% macro window_start() -%}
  ({{ as_of_date() }} - interval '{{ var("window_days") }} days')
{%- endmacro %}

{# Use a custom schema name as-is instead of prefixing it with the target schema. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
