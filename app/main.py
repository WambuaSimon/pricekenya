from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import admin, categories, meta, pages, products, reviews
from app.routes import alerts as alerts_routes
from db.session import init_db

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # Idempotent schema migrations. We don't (yet) use Alembic; each
    # migration is a one-shot ADD-COLUMN-IF-NOT-EXISTS or CREATE-TABLE-IF-
    # NOT-EXISTS. Safe to run every boot because each script no-ops when
    # its change already exists.
    # add_llm_extraction_log_table, add_product_embedding, and
    # add_product_merge_candidate_table are Simon's Phase 0/1 WIP; the
    # migration files live locally but haven't been committed yet. When
    # they land in HEAD, re-import + re-run them here.
    from db.migrations import (
        add_cached_sitemap_table,
        add_click_table,
        add_marketing_opt_in,
        add_product_description,
        add_review_moderation,
        add_reviews_table,
    )
    add_marketing_opt_in.run()
    add_click_table.run()
    add_product_description.run()
    add_reviews_table.run()
    add_review_moderation.run()
    add_cached_sitemap_table.run()
    yield


app = FastAPI(title="PriceKenya", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(pages.router)
app.include_router(products.router)
app.include_router(alerts_routes.router)
app.include_router(reviews.router)
app.include_router(categories.router)
app.include_router(meta.router)
app.include_router(admin.router)
