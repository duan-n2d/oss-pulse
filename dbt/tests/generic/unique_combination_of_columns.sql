{% test unique_combination_of_columns(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by all
having count(*) > 1
{% endtest %}
