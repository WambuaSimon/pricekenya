"""/internal/scrape/{target} — auth gating + target routing."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(session, monkeypatch):
    from app import config
    from app.main import app
    from db.session import get_session

    monkeypatch.setattr(config.settings, "admin_key", "top-secret")

    def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_401_without_key(client):
    resp = client.post("/internal/scrape/all-shopify")
    assert resp.status_code == 401


def test_404_when_admin_key_unset(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "admin_key", "")
    resp = client.post(
        "/internal/scrape/all-shopify", headers={"X-Admin-Key": "anything"}
    )
    # When ADMIN_KEY is unset in prod we return 404 to avoid confirming the
    # endpoint's existence — same defence-in-depth as /admin.
    assert resp.status_code == 404


def test_404_unknown_target(client):
    resp = client.post(
        "/internal/scrape/definitely-not-a-real-target",
        headers={"X-Admin-Key": "top-secret"},
    )
    assert resp.status_code == 404


def test_runs_target_through_executor(client, monkeypatch):
    """Auth + valid target dispatches to the executor and returns ok. Mocks
    the underlying target so we don't hit the network / DB."""
    calls: list[str] = []

    def _fake_target():
        calls.append("ran")

    from scrapers import ingest

    monkeypatch.setitem(ingest.TARGETS, "unit-test-target", _fake_target)

    resp = client.post(
        "/internal/scrape/unit-test-target",
        headers={"X-Admin-Key": "top-secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["target"] == "unit-test-target"
    assert "duration_seconds" in body
    assert calls == ["ran"]


def test_target_failure_returns_500_with_error_detail(client, monkeypatch):
    def _broken_target():
        raise RuntimeError("scraper blew up")

    from scrapers import ingest

    monkeypatch.setitem(ingest.TARGETS, "unit-test-broken", _broken_target)

    resp = client.post(
        "/internal/scrape/unit-test-broken",
        headers={"X-Admin-Key": "top-secret"},
    )
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"]["target"] == "unit-test-broken"
    assert "scraper blew up" in body["detail"]["error"]
