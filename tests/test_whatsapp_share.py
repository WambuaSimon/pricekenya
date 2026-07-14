"""Share + floating chat visibility: driven entirely by whether
PRICEKENYA_WHATSAPP_NUMBER is set.

The feature has three template surfaces:
  1. `/p/<slug>` product page — WhatsApp Share button (conditional) +
     Copy-link button (always).
  2. Every page (via base.html) — floating "Chat on WhatsApp" pill.
  3. `wa.me/<num>?text=…` URL format — verified by asserting the number
     round-trips through `whatsapp_href`.

All three must silently disappear when the number env is empty so we
never ship broken links to prod.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from app.context import whatsapp_href


@pytest.fixture()
def _set_wa_number(monkeypatch):
    """Force a number for the duration of one test."""
    from app.config import settings

    monkeypatch.setattr(settings, "pricekenya_whatsapp_number", "254712345678")
    yield


@pytest.fixture()
def _no_wa_number(monkeypatch):
    """Force the env-unset case."""
    from app.config import settings

    monkeypatch.setattr(settings, "pricekenya_whatsapp_number", "")
    yield


def test_whatsapp_href_returns_none_when_unset(_no_wa_number):
    assert whatsapp_href() is None
    assert whatsapp_href("Hi") is None


def test_whatsapp_href_builds_wa_me_url_with_encoded_message(_set_wa_number):
    href = whatsapp_href("Hi PriceKenya — I have a question.")
    assert href is not None
    assert href.startswith("https://wa.me/254712345678?text=")
    # The URL-encoded message must round-trip cleanly.
    encoded = href.split("?text=", 1)[1]
    assert unquote(encoded) == "Hi PriceKenya — I have a question."


def test_whatsapp_href_no_text_returns_bare_url(_set_wa_number):
    assert whatsapp_href() == "https://wa.me/254712345678"


def test_whitespace_number_treated_as_unset(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "pricekenya_whatsapp_number", "   ")
    assert whatsapp_href() is None


def test_floating_widget_hidden_when_number_unset(_no_wa_number):
    """base.html renders on any GET; the WA pill must not appear when
    the env is unset. Homepage is the cheapest page to smoke against."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.get("/")
    assert r.status_code == 200
    assert "data-wa-widget" not in r.text
    assert "wa.me" not in r.text


def test_floating_widget_renders_when_number_set(_set_wa_number):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.get("/")
    assert r.status_code == 200
    assert "data-wa-widget" in r.text
    assert "wa.me/254712345678" in r.text
    # Dismiss button and cookie logic must be present.
    assert "data-wa-dismiss" in r.text
    assert "pk_wa_dismissed" in r.text
