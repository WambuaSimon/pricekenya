import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

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


@app.middleware("http")
async def _neon_cold_start_retry(request: Request, call_next):
    """Retry idempotent (GET/HEAD) requests once when Neon compute is cold.

    Neon's free-tier Postgres suspends compute after ~5 minutes idle. The
    first request that arrives during the wake-up window can hit an SSL
    handshake timeout that pool_pre_ping can't catch (the pool is empty,
    so there's no cached socket to validate — the fresh connect is what
    fails). Sleep briefly to let compute finish booting, then replay.

    POST/PUT/PATCH/DELETE are NOT retried: they may have side effects
    (review submit, alert signup) that must never double-execute. Those
    still surface a 500 to the caller — one retry from the user's side
    is safer than silently repeating a mutation.
    """
    try:
        return await call_next(request)
    except OperationalError:
        if request.method not in ("GET", "HEAD"):
            raise
        await asyncio.sleep(1.5)
        return await call_next(request)


@app.middleware("http")
async def _admin_cookie_mirror(request: Request, call_next):
    """After a successful admin request that authenticated via ?admin_key= or
    X-Admin-Key header, mirror the key into an httpOnly cookie on the way
    out. That way the shared /admin nav tabs can navigate between subsystems
    without re-supplying the key on every click.

    Doing this in middleware (not in the require_admin dependency) because
    admin routes return TemplateResponse objects — cookies set on a
    Depends-injected Response get discarded when a new Response is returned.
    """
    response = await call_next(request)
    if not request.url.path.startswith("/admin"):
        return response
    if response.status_code >= 400:
        return response
    if request.cookies.get("admin_key"):
        return response
    provided = request.headers.get("x-admin-key") or request.query_params.get("admin_key")
    if not provided:
        return response
    from app.config import settings

    if not settings.admin_key or provided != settings.admin_key:
        return response
    response.set_cookie(
        "admin_key",
        settings.admin_key,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 8,
    )
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(pages.router)
app.include_router(products.router)
app.include_router(alerts_routes.router)
app.include_router(reviews.router)
app.include_router(categories.router)
app.include_router(meta.router)
app.include_router(admin.router)
