# Local workflow. The salt lives in .salt (git-ignored); create it once with `make salt`.
# In GitHub Actions it comes from the OSS_PULSE_SALT repository secret and must be the
# same value, or keys from different runs will not join.
export OSS_PULSE_SALT ?= $(shell cat .salt 2>/dev/null)
PY ?= python
FIXTURE := $(CURDIR)/build/fixture

.PHONY: install salt ingest build site docs report serve test lint fixture-build all

install:
	$(PY) -m pip install -e ".[dev]"

salt:
	@test -f .salt || $(PY) -c "import secrets; print(secrets.token_hex(24))" > .salt
	@echo "salt in .salt; set the same value as the OSS_PULSE_SALT repository secret"

ingest:
	oss-pulse ingest-github
	oss-pulse ingest-gharchive
	oss-pulse ingest-pypi

build:
	oss-pulse build

site:
	oss-pulse export-site

docs:
	cd dbt && dbt docs generate --static --profiles-dir .
	mkdir -p site/dbt-docs && cp dbt/target/static_index.html site/dbt-docs/index.html

report:
	oss-pulse report

serve: site
	$(PY) -m http.server 8000 --directory site

all: ingest build site docs report

test:
	pytest -q

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts

# Same as CI: deterministic fixture, offline dbt build, pinned analysis date.
fixture-build:
	rm -rf $(FIXTURE)
	OSS_PULSE_SALT=ci-fixture-salt-not-secret OSS_PULSE_DATA_DIR=$(FIXTURE) \
	  $(PY) scripts/make_fixture.py
	OSS_PULSE_SALT=ci-fixture-salt-not-secret OSS_PULSE_DATA_DIR=$(FIXTURE) \
	  OSS_PULSE_WAREHOUSE=$(FIXTURE)/warehouse.duckdb \
	  oss-pulse build --as-of 2026-06-30 --no-freshness
