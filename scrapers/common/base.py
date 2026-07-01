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
