"""Find active alerts whose target price is now satisfied and send emails.

v1: sends real transactional email via Resend. Falls back to stdout logging
if `RESEND_API_KEY` is unset (useful for local dev / CI without secrets).

Semantics:
- An alert with `target_price_kes = None` fires on the first run — any offer
  counts as a "notify me when this exists" signal.
- An alert with a target fires when `min_price <= target`.
- After a successful send we set `alert.active = False` (single-shot). The
  user re-subscribes from the product page if they want another notification;
  this avoids emailing daily while the price sits at target.
- If the Resend call fails, we leave the alert active so the next cron run
  retries.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
from sqlmodel import Session, func, select

from alerts.tokens import make_unsubscribe_token
from app.config import settings
from db.models import Alert, Listing, Product
from db.session import engine, init_db

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


def _render(product: Product, min_price: float, alert: Alert) -> tuple[str, str, str, str]:
    base = settings.base_url.rstrip("/")
    product_url = f"{base}/p/{product.slug}"
    unsub_url = f"{base}/alerts/unsubscribe/{make_unsubscribe_token(alert.id)}"

    subject = f"Price drop: {product.title} — KSh {int(min_price):,}"

    text = (
        f"Good news — {product.title} is now KSh {int(min_price):,} on PriceKenya.\n\n"
        f"See current offers: {product_url}\n\n"
        f"— PriceKenya\n"
        f"---\n"
        f"Unsubscribe from this alert: {unsub_url}\n"
    )

    html = f"""\
<!doctype html>
<html>
  <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#0f172a;max-width:560px;margin:0 auto;padding:24px;">
    <h2 style="color:#059669;margin:0 0 12px 0;font-size:20px;">Price drop alert</h2>
    <p style="line-height:1.5;"><strong>{product.title}</strong> is now <strong>KSh {int(min_price):,}</strong> on PriceKenya.</p>
    <p style="margin:24px 0;">
      <a href="{product_url}" style="display:inline-block;background:#059669;color:#ffffff;padding:10px 18px;text-decoration:none;border-radius:6px;font-weight:600;">See current offers</a>
    </p>
    <hr style="border:none;border-top:1px solid #e2e8f0;margin:32px 0 16px 0;">
    <p style="color:#64748b;font-size:12px;line-height:1.5;">
      You're receiving this because you set a price alert on
      <a href="{base}" style="color:#64748b;">PriceKenya</a>.<br>
      <a href="{unsub_url}" style="color:#64748b;">Unsubscribe from this alert</a>
    </p>
  </body>
</html>
"""
    return subject, text, html, unsub_url


def _send(to_email: str, subject: str, text: str, html: str, unsub_url: str) -> bool:
    if not settings.resend_api_key:
        log.warning("RESEND_API_KEY unset — logging alert instead of sending")
        # Deliberately don't log the email address here: GH Actions logs are
        # readable by every collaborator on the repo.
        print(f"[alerts] would send: {subject}")
        return False
    try:
        resp = httpx.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.alerts_from_email,
                "to": [to_email],
                "subject": subject,
                "text": text,
                "html": html,
                # Gmail/Outlook use this to render a native unsubscribe button
                # in the message header and to satisfy their bulk-sender rules.
                "headers": {
                    "List-Unsubscribe": f"<{unsub_url}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                },
            },
            timeout=15.0,
        )
        if resp.status_code >= 400:
            log.error("Resend %s: %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception:  # noqa: BLE001
        log.exception("Resend send failed")
        return False


def run() -> None:
    init_db()
    with Session(engine) as session:
        rows = session.exec(
            select(Alert, Product, func.min(Listing.price_kes).label("min_price"))
            .join(Product, Product.id == Alert.product_id)
            .join(Listing, Listing.product_id == Product.id)
            .where(Alert.active == True)  # noqa: E712
            .group_by(Alert.id, Product.id)
        ).all()

        sent = 0
        skipped = 0
        for alert, product, min_price in rows:
            if min_price is None:
                skipped += 1
                continue
            if alert.target_price_kes is not None and min_price > alert.target_price_kes:
                skipped += 1
                continue

            subject, text, html, unsub_url = _render(product, float(min_price), alert)
            if _send(alert.email, subject, text, html, unsub_url):
                alert.last_notified_at = datetime.utcnow()
                alert.active = False  # single-shot; user re-subscribes if desired
                session.add(alert)
                sent += 1
            else:
                skipped += 1

        session.commit()
        # Aggregate counts only — never the emails themselves (PII, logs are
        # readable by every collaborator on public/private GH repos).
        print(f"[alerts] sent={sent} skipped={skipped}")


if __name__ == "__main__":
    run()
