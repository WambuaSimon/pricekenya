"""Internal endpoints for running scrapes from Render's outbound IP.

Some merchants (mostly Shopify stores on Cloudflare/Sucuri) block or
return empty payloads to requests from GitHub Actions runner IPs — the
Azure DC ranges get flagged by generic bot-reputation lists. Running the
same fetch from Render (Frankfurt DC, cleaner reputation) sidesteps
the block cleanly.

The `scrape.yml` matrix legs that need this trigger the scrape via
`curl -X POST https://<host>/internal/scrape/<target>` instead of running
`python -m scrapers.ingest <target>` locally.

Auth: X-Admin-Key header (same shared secret as /admin/*).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query

from app.config import settings

router = APIRouter(prefix="/internal", tags=["internal"])


def _require_admin(
    x_admin_key: str | None = Header(default=None),
    admin_key_cookie: str | None = Cookie(default=None, alias="admin_key"),
    admin_key_query: str | None = Query(default=None, alias="admin_key"),
) -> None:
    if not settings.admin_key:
        raise HTTPException(status_code=404)
    provided = x_admin_key or admin_key_cookie or admin_key_query
    if not provided or provided != settings.admin_key:
        raise HTTPException(status_code=401, detail="admin key required")


# Dedicated single-thread executor for scrape runs. Sizing = 1 because a
# scrape hits the DB heavily and holding two parallel scrapes on a shared
# Neon compute would spike CU-hours and defeat the point of the recent
# max-parallel: 5 cap on GH Actions. Requests queue on this pool.
_SCRAPE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scrape")


@router.post("/scrape/{target}")
async def run_scrape(
    target: str,
    _: None = Depends(_require_admin),
) -> dict:
    """Run one entry from `scrapers.ingest.TARGETS` synchronously.

    Blocks until the scrape finishes — Shopify batch runs typically 30-90s
    per merchant; the full `all-shopify` target is 3-5 minutes. Uses a
    dedicated ThreadPoolExecutor so the sync `asyncio.run(_consume(...))`
    body doesn't collide with FastAPI's outer event loop.

    Returns {status, target, duration_seconds}. Non-2xx status codes on
    failure so CI matrix legs treat them as job failures.
    """
    from scrapers.ingest import TARGETS

    fn = TARGETS.get(target)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"unknown target: {target}")

    loop = asyncio.get_running_loop()
    started = datetime.utcnow()
    try:
        await loop.run_in_executor(_SCRAPE_EXECUTOR, fn)
    except Exception as exc:  # noqa: BLE001
        duration = (datetime.utcnow() - started).total_seconds()
        raise HTTPException(
            status_code=500,
            detail={
                "target": target,
                "error": f"{type(exc).__name__}: {exc}",
                "duration_seconds": round(duration, 1),
            },
        ) from exc

    return {
        "status": "ok",
        "target": target,
        "duration_seconds": round((datetime.utcnow() - started).total_seconds(), 1),
    }
