select distinct bot_key, bot_login
from {{ source('raw', 'bot_keys') }}
