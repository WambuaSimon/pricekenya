"""Signed tokens for one-click unsubscribe links.

Uses HMAC-SHA256 with the app's `SECRET_KEY` so tokens can't be forged from
just knowing an alert ID. The token encodes the alert id in plaintext so the
unsubscribe route can find the row without scanning — the signature is only
there to prove the URL originated from us.

Format: `<alert_id>.<base64url(hmac-sha256)>`

If `SECRET_KEY` is unset, signing still produces a deterministic token but
anyone who reads this code could forge one. Fail-loud in prod: check that
`settings.secret_key` is populated at startup.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from app.config import settings


def _sig(payload: str) -> str:
    mac = hmac.new(
        settings.secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def make_unsubscribe_token(alert_id: int) -> str:
    payload = str(alert_id)
    return f"{payload}.{_sig(payload)}"


def verify_unsubscribe_token(token: str) -> int | None:
    """Return the alert_id if the token is valid, else None."""
    try:
        payload, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sig(payload)):
        return None
    try:
        return int(payload)
    except ValueError:
        return None
