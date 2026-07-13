"""Shared scraper utilities: polite HTTP, retries, raw-listing dataclass."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings


@dataclass
class RawListing:
    merchant_slug: str
    merchant_sku: str | None
    url: str
    title: str
    price_kes: Decimal
    in_stock: bool
    image_url: str | None
    # Category slug the scraper knows this listing belongs to (e.g. "phones",
    # "laptops"). The ingest pipeline uses this to route to the right matcher.
    category_slug: str = "phones"


class PoliteClient:
    """httpx.AsyncClient wrapper with a fixed UA and a per-request delay."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": settings.scraper_user_agent},
            timeout=30.0,
            follow_redirects=True,
        )
        self._delay = settings.scraper_request_delay_seconds

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get(self, url: str) -> httpx.Response:
        resp = await self._client.get(url)
        resp.raise_for_status()
        await asyncio.sleep(self._delay)
        return resp

    async def aclose(self) -> None:
        await self._client.aclose()


class PlaywrightPoliteClient:
    """Headless Chromium wrapper for sites behind JS-challenge shields
    (Cloudflare Turnstile etc.) that curl_cffi's TLS impersonation can't
    resolve on its own.

    Same interface as PoliteClient / CffiPoliteClient — one .get(url) call
    yields an object with .text and .raise_for_status(). Chromium launches
    lazily on first use and is reused across .get() calls, so the browser
    startup cost is paid once per scrape run, not once per URL.

    stealth=True applies playwright-stealth patches (hides navigator.web-
    driver, adds missing plugins, spoofs webGL vendor etc.) to defeat the
    newer Turnstile variants that fingerprint headless Chromium. Not every
    merchant needs it — try without first because stealth adds ~1s startup
    overhead per browser launch.
    """

    def __init__(self, user_agent: str | None = None, stealth: bool = False) -> None:
        self._ua = user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        self._stealth = stealth
        self._playwright = None
        self._browser = None
        self._context = None
        self._pw_ctxmgr = None  # holds the async_playwright() ctx when stealth wraps it
        self._delay = settings.scraper_request_delay_seconds

    async def _ensure_browser(self) -> None:
        if self._context is not None:
            return
        # Deferred imports so environments without playwright installed can
        # still import this module (httpx-based scrapers keep working).
        from playwright.async_api import async_playwright

        if self._stealth:
            from playwright_stealth import Stealth

            self._pw_ctxmgr = Stealth().use_async(async_playwright())
            self._playwright = await self._pw_ctxmgr.__aenter__()
        else:
            self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(user_agent=self._ua)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get(self, url: str) -> _PWResponse:
        await self._ensure_browser()
        page = await self._context.new_page()
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            # Give any JS challenge time to resolve. Turnstile's invisible-
            # challenge flow usually clears in 2-4s. 4s is a generous median
            # that keeps per-page cost bounded — with 3 pages × dozens of
            # URLs, every extra second here compounds into a job timeout.
            await asyncio.sleep(4)
            try:
                await page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:  # noqa: BLE001
                pass
            html = await page.content()
            status = resp.status if resp else 0
            await asyncio.sleep(self._delay)
            # DO NOT reject on status alone. Cloudflare frequently serves
            # the initial navigation with 403 while the Turnstile JS runs,
            # then the browser reloads/re-renders with the real DOM. We
            # care about the final DOM, not the first response's status.
            # Only raise when we're still looking at the challenge page.
            title = await page.title()
            if title == "Just a moment..." or "cf-mitigated" in html.lower()[:5000]:
                raise RuntimeError(
                    f"Cloudflare challenge unresolved on {url} "
                    f"(status={status}, title={title!r})"
                )
            return _PWResponse(text=html, status_code=status)
        finally:
            await page.close()

    async def aclose(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()


class _PWResponse:
    """Minimal response shim — the scrapers only use `.text` on the response
    object. Kept out of dataclass to avoid pydantic collisions."""

    def __init__(self, text: str, status_code: int) -> None:
        self.text = text
        self.status_code = status_code


class CffiPoliteClient:
    """curl_cffi async client with a Chrome TLS fingerprint.

    Some Kenyan merchants (Naivas, Phone Place) sit behind Cloudflare and
    fingerprint the TLS handshake — plain httpx gets a 403 regardless of UA.
    curl_cffi impersonates Chrome's TLS ClientHello and gets through cleanly.
    Interface mirrors PoliteClient so scrapers can pick either.
    """

    def __init__(self, impersonate: str = "chrome") -> None:
        # Deferred import so environments without curl_cffi installed still
        # import the module (httpx-based scrapers keep working).
        from curl_cffi.requests import AsyncSession

        self._session = AsyncSession(impersonate=impersonate, timeout=30)
        self._delay = settings.scraper_request_delay_seconds

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get(self, url: str):
        resp = await self._session.get(url)
        resp.raise_for_status()
        await asyncio.sleep(self._delay)
        return resp

    async def aclose(self) -> None:
        await self._session.close()
