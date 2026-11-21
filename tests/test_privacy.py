import duckdb
import pytest

from oss_pulse.privacy import MissingSaltError, get_salt, is_bot, pseudonymize


def test_key_is_stable_case_insensitive_and_salted(salt):
    a = pseudonymize("Duan-N2D", salt)
    assert a == pseudonymize("duan-n2d", salt)
    assert a != pseudonymize("duan-n2d", salt + "x")
    assert len(a) == 16
    int(a, 16)  # hex


def test_missing_login_stays_missing(salt):
    assert pseudonymize(None, salt) is None


def test_python_and_duckdb_hashes_agree(salt):
    """GH Archive keys are computed in DuckDB, PR keys in Python: they must match."""
    sql_key = duckdb.execute(
        "select substr(sha256(? || ':' || lower(?)), 1, 16)", [salt, "Some-User"]
    ).fetchone()[0]
    assert sql_key == pseudonymize("Some-User", salt)


def test_short_or_missing_salt_is_refused(monkeypatch):
    monkeypatch.setenv("OSS_PULSE_SALT", "short")
    with pytest.raises(MissingSaltError):
        get_salt()
    monkeypatch.delenv("OSS_PULSE_SALT")
    with pytest.raises(MissingSaltError):
        get_salt()


@pytest.mark.parametrize(
    ("login", "typename", "expected"),
    [
        ("dependabot[bot]", "Bot", True),
        ("codecov", "Bot", True),
        ("boring-cyborg", "User", True),
        ("my-ci-bot", "User", True),
        ("robotics-fan", "User", False),
        ("alice", "User", False),
        (None, None, False),
    ],
)
def test_bot_detection(login, typename, expected):
    assert is_bot(login, typename) is expected
