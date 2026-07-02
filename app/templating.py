from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.context import get_nav_categories

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def kes(value) -> str:
    try:
        return f"KSh {int(value):,}"
    except (TypeError, ValueError):
        return "—"


templates.env.filters["kes"] = kes
templates.env.globals["nav_categories"] = get_nav_categories
