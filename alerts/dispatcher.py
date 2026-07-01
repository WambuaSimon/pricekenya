"""Find active alerts whose target price is now satisfied and send emails.

v0: emits to stdout. Wire SMTP later via app.config.settings.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, func, select

from db.models import Alert, Listing, Product
from db.session import engine, init_db


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

        for alert, product, min_price in rows:
            if min_price is None:
                continue
            if alert.target_price_kes is None or min_price <= alert.target_price_kes:
                print(
                    f"[ALERT] {alert.email}: {product.title} is now KSh {int(min_price):,}"
                )
                alert.last_notified_at = datetime.utcnow()
                session.add(alert)
        session.commit()


if __name__ == "__main__":
    run()
