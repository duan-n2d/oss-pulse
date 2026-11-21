from __future__ import annotations

import pytest

SALT = "unit-test-salt-0123456789"


@pytest.fixture(autouse=True)
def _salt_env(monkeypatch):
    monkeypatch.setenv("OSS_PULSE_SALT", SALT)


@pytest.fixture
def salt() -> str:
    return SALT
