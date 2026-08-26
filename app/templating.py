from datetime import UTC, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.context import (
    get_active_top_slug,
    get_nav_categories,
    product_fallback_label,
    product_placeholder_icon,
    whatsapp_href,
)
from app.pricing import trusted_saving

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def kes(value) -> str:
    # "n/a" rather than an em dash: the revamp strips em dashes from all
    # user-visible copy, and this fallback renders inside price slots.
    try:
        return f"KSh {int(value):,}"
    except (TypeError, ValueError):
        return "n/a"


templates.env.filters["kes"] = kes
templates.env.globals["nav_categories"] = get_nav_categories
templates.env.globals["get_active_top_slug"] = get_active_top_slug
templates.env.globals["product_placeholder_icon"] = product_placeholder_icon
templates.env.globals["product_fallback_label"] = product_fallback_label
templates.env.globals["whatsapp_href"] = whatsapp_href
templates.env.globals["trusted_saving"] = trusted_saving
templates.env.globals["now"] = lambda: datetime.now(UTC)
