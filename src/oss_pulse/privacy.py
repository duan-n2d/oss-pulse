"""Pseudonymisation of GitHub logins.

Logins are hashed with a secret salt *before* anything is written to the landing
zone, because the landing zone is published on a public branch. The same salt gives
the same key, so joins (PR author vs reviewer) still work; without the salt a key
cannot be reversed by hashing a list of known logins.
"""

from __future__ import annotations

import hashlib
import os

SALT_ENV = "OSS_PULSE_SALT"
MIN_SALT_LEN = 16


class MissingSaltError(RuntimeError):
    pass


def get_salt() -> str:
    salt = os.environ.get(SALT_ENV, "")
    if len(salt) < MIN_SALT_LEN:
        raise MissingSaltError(
            f"{SALT_ENV} must be set to a secret of at least {MIN_SALT_LEN} characters"
        )
    return salt


def pseudonymize(login: str | None, salt: str) -> str | None:
    """Return a stable 16-hex-char key for a login, or None for a missing author."""
    if login is None:
        return None
    digest = hashlib.sha256(f"{salt}:{login.lower()}".encode()).hexdigest()
    return digest[:16]


def is_bot(login: str | None, typename: str | None) -> bool:
    if typename == "Bot":
        return True
    if login is None:
        return False
    low = login.lower()
    return low.endswith("[bot]") or low.endswith("-bot") or low in KNOWN_BOTS


# Accounts that act as bots but are typed as User by the API.
KNOWN_BOTS = frozenset(
    {
        "asfgit",
        "codecov-commenter",
        "github-actions",
        "dependabot",
        "renovate",
        "pre-commit-ci",
        "sonarcloud",
        "netlify",
        "vercel",
        "boring-cyborg",
        "polars-bot",
    }
)
