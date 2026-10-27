"""Share + floating chat visibility.

Two independent switches, deliberately not one:

  PRICEKENYA_WHATSAPP_NUMBER         do we have a number at all
  PRICEKENYA_WHATSAPP_CHAT_ENABLED   is anyone reading it (default: no)

The number alone governs the product page's *share* button, which is
user-to-user and obliges us nothing. Both must be true for the *inbound*
surfaces — the floating pill and the footer link — because those invite a
shopper to message us, and an unread inbox reads as an abandoned site.

Template surfaces:
  1. `/p/<slug>` product page — Share button (number only) + Copy-link
     (always, needs no config).
  2. Every page, via base.html — floating "Chat on WhatsApp" pill AND the
     footer WhatsApp link. Both inbound; both need the chat flag too.
  3. `wa.me/<num>?text=…` URL format — verified by asserting the number
     round-trips through `whatsapp_href`.

All of them must silently disappear rather than render a broken or
unattended link.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from app.context import whatsapp_chat_href, whatsapp_href


@pytest.fixture()
def _set_wa_number(monkeypatch):
    """Force a number for the duration of one test. Chat stays OFF — that is
    the shipped default, so this fixture reflects production."""
    from app.config import settings

    monkeypatch.setattr(settings, "pricekenya_whatsapp_number", "254712345678")
    monkeypatch.setattr(settings, "pricekenya_whatsapp_chat_enabled", False)
    yield


@pytest.fixture()
def _chat_on(monkeypatch, _set_wa_number):
    """Number set AND inbound chat switched on."""
    from app.config import settings

    monkeypatch.setattr(settings, "pricekenya_whatsapp_chat_enabled", True)
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


def test_floating_widget_renders_when_chat_enabled(_chat_on):
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


# --------------------------------------------------------------------------
# The chat flag, added 2026-10-27 to take the inbound surfaces down without
# taking sharing down with them.


def test_chat_href_none_when_flag_off_even_with_number(_set_wa_number):
    """The default. A number on file is not consent to be messaged."""
    assert whatsapp_chat_href() is None


def test_chat_href_none_when_flag_on_but_no_number(monkeypatch, _no_wa_number):
    from app.config import settings

    monkeypatch.setattr(settings, "pricekenya_whatsapp_chat_enabled", True)
    assert whatsapp_chat_href() is None


def test_chat_href_set_when_both_on(_chat_on):
    assert whatsapp_chat_href() == "https://wa.me/254712345678"


def test_share_href_survives_chat_being_off(_set_wa_number):
    """The point of two switches. Turning inbound chat off must not cost us
    the product page's share button, which is this site's cheapest
    distribution in a market that runs on WhatsApp."""
    href = whatsapp_href("Tecno Spark 30C - from KSh 14,999 - https://x/p/y")
    assert href is not None
    assert href.startswith("https://wa.me/254712345678?text=")


def test_pill_and_footer_link_both_hidden_when_flag_off(_set_wa_number):
    """Hiding the pill but leaving the footer link would not be hiding the
    feature — both open the same empty compose addressed to us."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.get("/")
    assert r.status_code == 200
    assert "data-wa-widget" not in r.text, "floating pill still rendered"
    # The footer link is the other inbound surface and shares _chat_href, so
    # no wa.me URL should survive anywhere on a page with no share button.
    assert "wa.me" not in r.text, "a wa.me link survived somewhere on the page"
