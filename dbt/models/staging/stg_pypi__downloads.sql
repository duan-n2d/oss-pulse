-- pypistats re-serves its whole rolling window on every call; keep the newest
-- observation of each package-day.
select distinct on (package, download_date)
    package,
    repo,
    download_date,
    downloads,
    ingested_at
from {{ source('raw', 'pypi_downloads') }}
order by package, download_date, ingested_at desc
