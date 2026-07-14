"""Shared pytest fixtures.

`session`: an isolated in-memory sqlite Session with the full schema created.
Use this whenever a test touches the DB layer.

We patch `db.session.engine` so any module that reaches out to it (migrations,
match.py, llm_extract.py) sees the same in-memory engine as the test session.
"""

from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


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
    """
    from sqlmodel import SQLModel

    from db import models  # noqa: F401 — register tables in metadata
    from db.session import engine as default_engine

    SQLModel.metadata.create_all(default_engine)
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
