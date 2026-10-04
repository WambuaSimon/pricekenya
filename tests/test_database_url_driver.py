"""DATABASE_URL must always resolve to psycopg3.

`psycopg2` is not installed (pyproject pins `psycopg[binary]`), so a bare
`postgresql://` URL — which is what Render's dashboard and Blueprint
`fromDatabase` both emit — would make SQLAlchemy reach for a driver that
isn't there. app.config normalises the scheme so that can't happen.
"""
import pytest

from app.config import Settings


@pytest.mark.parametrize(
    "given,expected",
    [
        # Bare schemes, as handed out by Render / Neon / Heroku dashboards.
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        # Already correct — normalisation is idempotent.
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        # A different explicit driver is still redirected: psycopg2 is absent.
        ("postgresql+psycopg2://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        # Query strings and internal (port-less) hosts survive intact.
        ("postgresql://u:p@dpg-abc/db?sslmode=require",
         "postgresql+psycopg://u:p@dpg-abc/db?sslmode=require"),
        # Non-Postgres passes through untouched.
        ("sqlite:///./pricekenya.db", "sqlite:///./pricekenya.db"),
    ],
)
def test_scheme_normalised_to_psycopg3(given, expected):
    assert Settings(database_url=given).database_url == expected


def test_malformed_value_is_not_mangled():
    """No '://' means we can't reason about it — hand it back unchanged
    rather than inventing a scheme."""
    assert Settings(database_url="not-a-url").database_url == "not-a-url"


def test_psycopg3_is_the_driver_actually_installed():
    """Guards the premise: if psycopg2 ever gets installed and psycopg3
    dropped, the normalisation above would be actively wrong."""
    import importlib.util

    assert importlib.util.find_spec("psycopg") is not None
