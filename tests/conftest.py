"""Shared pytest fixtures.

`session`: an isolated in-memory sqlite Session with the full schema created.
Use this whenever a test touches the DB layer.

We patch `db.session.engine` so any module that reaches out to it (migrations,
match.py, llm_extract.py) sees the same in-memory engine as the test session.
"""

from __future__ import annotations

import os
import sys

# Pin the suite to a throwaway SQLite file BEFORE anything imports
# app.config, which reads DATABASE_URL once at import time.
#
# Without this the suite inherits the developer's .env. On a machine where
# that points at Neon — which it does, the prod URL is the last DATABASE_URL
# line in .env and therefore wins — the session-scoped fixture below ran
# SQLModel.metadata.create_all() against PRODUCTION on every `pytest`
# invocation, reflecting the live schema and standing ready to issue DDL
# against it. Tests should never depend on which database a developer
# happens to be pointed at.
os.environ["DATABASE_URL"] = "sqlite:///./.pytest-pricekenya.db"

import pytest  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_default_engine_tables():
    """Ensure the process-level engine has the schema before any test runs.

    Some tests instantiate TestClient(app) WITHOUT the `with … as` context
    manager (test_reviews.py, test_sitemap_cache.py, test_admin_merge_review
    .py). That skips FastAPI's lifespan hook, so init_db() never fires and
    handlers hit an empty SQLite. Locally the ./pricekenya.db file already
    has tables from previous boots, so the tests pass; on CI's fresh runner
    they explode with "no such table". Creating the schema here removes the
    CI-vs-local drift without having to rewrite each caller.

    DATABASE_URL is pinned to a throwaway SQLite file at the top of this
    module, so `default_engine` is always local. The assertion below is a
    tripwire, not a fallback: if it ever fires, something imported
    app.config before conftest ran and this fixture is one create_all away
    from reflecting a real database.
    """
    from sqlmodel import SQLModel

    from db import models  # noqa: F401 — register tables in metadata
    from db.session import engine as default_engine

    assert default_engine.dialect.name == "sqlite", (
        f"Test suite is pointed at {default_engine.dialect.name}, not SQLite. "
        "Refusing to run schema DDL against it."
    )
    SQLModel.metadata.create_all(default_engine)

    # Seed sample rows if the scratch DB is empty, mirroring the "Seed sample
    # DB" step in .github/workflows/ci.yml.
    #
    # test_reviews.py and test_sitemap_cache.py drive handlers against real
    # Product rows via the process-level engine rather than the in-memory
    # `session` fixture. Their comment says they "lean on whatever local
    # sqlite has" — but with DATABASE_URL pointed at Neon that was whatever
    # PRODUCTION had, so those tests were reading live data and passing
    # because of it. Seeding here makes a local run reproduce CI exactly and
    # keeps the suite off any real database.
    from sqlmodel import Session as _Session
    from sqlmodel import select as _select

    from db.models import Product as _Product

    with _Session(default_engine) as s:
        already_seeded = s.exec(_select(_Product).limit(1)).first() is not None
    if not already_seeded:
        from seed.load import run as seed_run

        seed_run()
    yield


def pytest_sessionfinish(session, exitstatus):
    """Force a clean exit once pytest has already reported success.

    sentence-transformers pulls in torch, and torch's native destructors
    occasionally segfault during CPython interpreter shutdown on macOS.
    That crash lands AFTER pytest has printed "N passed" but flips the
    process exit code, which the pre-push hook then treats as failure.

    Calling `os._exit` bypasses the Python-level atexit / finalizer chain
    entirely — safe once pytest is done because there's nothing left to
    flush at the app level. Only fires when the test suite itself passed.
    """
    if exitstatus == 0:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


@pytest.fixture
def session(monkeypatch):
    # StaticPool + shared connection so every Session opened against this
    # engine sees the same in-memory database (default SQLite-in-memory
    # gives each connection its own private DB).
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Import models so their tables are registered in metadata.
    from db import models  # noqa: F401
    SQLModel.metadata.create_all(engine)

    # Redirect any code that reads db.session.engine to our test engine.
    import db.session as db_session

    monkeypatch.setattr(db_session, "engine", engine)
    # Modules that did `from db.session import engine` at import time hold a
    # stale reference; rebind them explicitly if already loaded.
    import sys
    for mod_name in ("app.context",):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "engine"):
            monkeypatch.setattr(mod, "engine", engine)

    with Session(engine) as s:
        yield s
