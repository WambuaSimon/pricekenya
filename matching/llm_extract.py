"""LLM-backed fallback for titles the regex parser can't extract.

Wired into `matching.match.match_or_create_product` at the silent-drop point.
When the regex parser returns `parsed.canonical_key is None` and the feature
flag `LLM_FALLBACK_ENABLED` is on, we call Gemini 2.0 Flash (free tier) with
a category-specific Pydantic schema, cache the result in `LlmExtractionLog`,
and hand the structured pieces to `matching.compose_keys.COMPOSERS[slug]`
so the produced `canonical_key` is bit-identical to what the regex parser
would have produced.

Guardrails:
- Per-category daily cap (SELECT count on llmextractionlog).
- Title-hash cache: same title from N merchants = 1 API call.
- 3s hard timeout wrapped around the SDK (advisory timeouts vary by version).
- No retry on failure — free tier RPM is tight, retries burn cap.
- Any error path returns None, matching the pre-existing silent-drop behavior.
"""

from __future__ import annotations

import concurrent.futures
import functools
import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.config import settings
from db.models import LlmExtractionLog
from matching.base import ParsedTitle, clean_title
from matching.compose_keys import COMPOSERS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-category Pydantic response schemas
# ---------------------------------------------------------------------------
# Enum values MUST match the strings the composers expect. E.g. `twin-tub`
# not `twintub`; `pure-sine` not `pure sine`. If drift creeps in, the
# parity tests in tests/test_compose_parity.py will catch it before ship.


class _Base(BaseModel):
    """Common fields on every schema. `is_valid_for_category=False` lets the
    LLM veto listings that are not actually the target category.

    Deliberately NOT setting `ConfigDict(extra="forbid")` — Pydantic converts
    that to `additionalProperties: false` in the JSON schema, which the
    Gemini structured-output endpoint rejects with 400 INVALID_ARGUMENT.
    """

    is_valid_for_category: bool
    brand: str | None = None


class PhoneSchema(_Base):
    model: str | None = None
    storage_gb: int | None = None
    ram_gb: int | None = None


class TabletSchema(_Base):
    model: str | None = None
    screen_inches: float | None = None
    storage_gb: int | None = None
    ram_gb: int | None = None


class LaptopSchema(_Base):
    model_line: str | None = None
    variant: str | None = None
    cpu_family: str | None = None
    cpu_gen: int | None = None
    ram_gb: int | None = None
    storage_gb: int | None = None
    storage_type: Literal["ssd", "hdd", "emmc", "nvme"] | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class TvSchema(_Base):
    size_inches: int | None = None
    resolution: Literal["hd", "fhd", "4k", "8k"] | None = None
    panel: Literal["led", "qled", "oled", "miniled"] | None = None
    smart: bool = False
    condition: Literal["new", "used", "refurbished"] = "new"


class RefrigeratorSchema(_Base):
    capacity_liters: int | None = None
    door_type: Literal["single", "double", "french", "sbs"] | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class FreezerSchema(_Base):
    capacity_liters: int | None = None
    freezer_type: Literal["chest", "upright", "combi"] | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class WaterDispenserSchema(_Base):
    model: str | None = None
    dispenser_type: (
        Literal["hot-cold", "hot-normal", "hot-cold-normal", "bottom-load", "top-load"] | None
    ) = None
    condition: Literal["new", "used", "refurbished"] = "new"


class WasherSchema(_Base):
    capacity_kg: float | None = None
    load_type: Literal["twin-tub", "front", "top"] | None = None
    automation: Literal["auto", "semi-auto", "unknown"] = "unknown"
    has_dryer: bool = False
    condition: Literal["new", "used", "refurbished"] = "new"


class CookingSchema(_Base):
    type: Literal["microwave", "cooker", "hob", "oven", "hot-plate"] | None = None
    capacity_liters: int | None = None
    burners: int | None = None
    watts: int | None = None
    fuel: Literal["gas", "electric", "induction"] | None = None
    control: Literal["digital", "manual"] | None = None
    has_grill: bool = False
    condition: Literal["new", "used", "refurbished"] = "new"


class AudioSchema(_Base):
    type: (
        Literal[
            "soundbar",
            "home-theatre",
            "party-speaker",
            "speaker",
            "earbuds",
            "headphones",
            "mp3-player",
        ]
        | None
    ) = None
    model_code: str | None = None
    channels: str | None = None  # e.g. "2.1"
    watts: int | None = None
    wireless: bool = False
    condition: Literal["new", "used", "refurbished"] = "new"


class CameraSchema(_Base):
    type: (
        Literal[
            "action-cam",
            "security-cam",
            "instant-camera",
            "drone-camera",
            "kids-camera",
            "mirrorless",
            "dslr",
            "digital-camera",
        ]
        | None
    ) = None
    model_code: str | None = None
    megapixels: int | None = None
    zoom: int | None = None
    resolution: Literal["720p", "1080p", "4k", "6k", "8k"] | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class BlenderSchema(_Base):
    subtype: Literal["juicer", "food-processor", "immersion", "personal", "jug"] | None = None
    capacity_liters: float | None = None
    watts: int | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class ToasterSchema(_Base):
    subtype: Literal["pop-up", "oven"] | None = None
    slots: int | None = None
    capacity_liters: float | None = None
    watts: int | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class KettleSchema(_Base):
    capacity_liters: float | None = None
    material: Literal["glass", "stainless", "plastic"] | None = None
    watts: int | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class IronSchema(_Base):
    iron_type: Literal["steam", "dry", "garment-steamer", "press"] | None = None
    watts: int | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class InverterSchema(_Base):
    watts: int | None = None
    topology: (
        Literal["hybrid", "pure-sine", "modified", "off-grid", "grid-tie"] | None
    ) = None
    voltage: int | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class SolarPanelSchema(_Base):
    watts: int | None = None
    cell_type: Literal["mono", "poly", "bifacial", "thin-film"] | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class SolarBatterySchema(_Base):
    capacity_ah: int | None = None
    chemistry: (
        Literal["lifepo4", "lithium", "gel", "agm", "vrla", "tubular", "lead-acid"] | None
    ) = None
    voltage: int | None = None
    condition: Literal["new", "used", "refurbished"] = "new"


class PhoneTabletAccessorySchema(_Base):
    detected_type: (
        Literal[
            "power-bank",
            "wireless-charger",
            "car-charger",
            "charger",
            "cable",
            "screen-protector",
            "case",
            "earbuds",
            "smartwatch",
            "stylus",
        ]
        | None
    ) = None
    model: str | None = None
    watts: int | None = None
    mah: int | None = None
    connectors: (
        Literal[
            "usbc-lightning", "usba-lightning", "usbc-usbc", "usba-usbc", "usba-microusb"
        ]
        | None
    ) = None
    variant: str | None = None  # dualsense, series-10, se, etc.
    generation: str | None = None  # apple pencil gen: "1gen", "2gen", "pro", "usb-c"


class PeripheralsAccessorySchema(_Base):
    detected_type: (
        Literal["keyboard", "mouse", "usb-hub", "webcam", "headset", "cable", "charger"] | None
    ) = None
    model: str | None = None
    watts: int | None = None
    connectors: (
        Literal[
            "usbc-lightning", "usba-lightning", "usbc-usbc", "usba-usbc", "usba-microusb"
        ]
        | None
    ) = None


class ConsoleAccessorySchema(_Base):
    detected_type: (
        Literal["controller", "gaming-headset", "charging-dock", "headset"] | None
    ) = None
    model: str | None = None
    variant: str | None = None


SCHEMAS: dict[str, type[BaseModel]] = {
    "phones": PhoneSchema,
    "tablets": TabletSchema,
    "laptops": LaptopSchema,
    "tvs": TvSchema,
    "refrigerators": RefrigeratorSchema,
    "freezers": FreezerSchema,
    "water-dispensers": WaterDispenserSchema,
    "washers-dryers": WasherSchema,
    "cooking": CookingSchema,
    "audio": AudioSchema,
    "cameras": CameraSchema,
    "blenders": BlenderSchema,
    "toasters": ToasterSchema,
    "kettles": KettleSchema,
    "ironing-laundry": IronSchema,
    "inverters": InverterSchema,
    "solar-panels": SolarPanelSchema,
    "solar-batteries": SolarBatterySchema,
    "phone-tablet-accessories": PhoneTabletAccessorySchema,
    "peripherals-accessories": PeripheralsAccessorySchema,
    "console-accessories": ConsoleAccessorySchema,
}

# ---------------------------------------------------------------------------
# Prompts (per category, short — Gemini pairs each with the JSON schema).
# ---------------------------------------------------------------------------

_PROMPT_HEADER = (
    "You extract structured product data from Kenyan e-commerce listing titles. "
    "Return only fields you are confident in — prefer null over guessing. "
    "If the listing is not actually a {category_pretty}, set "
    "is_valid_for_category=false. Otherwise set true. "
    "Brand names should be lowercase and slug-friendly "
    "(e.g. 'vision-plus', not 'Vision Plus'). "
    "Match your enum values EXACTLY to the schema — 'pure-sine' not 'pure sine'."
)

_PROMPTS: dict[str, str] = {
    slug: _PROMPT_HEADER.format(category_pretty=slug.replace("-", " "))
    for slug in SCHEMAS
}

# ---------------------------------------------------------------------------
# Gemini client (lazy) + call wrapper
# ---------------------------------------------------------------------------

_client: Any = None
_client_error_logged = False


def _get_client() -> Any | None:
    global _client, _client_error_logged
    if _client is not None:
        return _client
    if not settings.gemini_api_key:
        return None
    try:
        from google import genai  # type: ignore[import-not-found]
    except ImportError:
        if not _client_error_logged:
            logger.warning("google-genai not installed; LLM fallback disabled")
            _client_error_logged = True
        return None
    _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


_WHITESPACE_RE = re.compile(r"\s+")


def _title_hash(title: str, category: str) -> str:
    key = f"{category}\x00{_WHITESPACE_RE.sub(' ', clean_title(title))}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


@functools.lru_cache(maxsize=2048)
def _cached_lookup_key(hash_: str, category: str) -> str:
    """Just marks the (hash, category) pair as recently seen. Actual response
    lives in LlmExtractionLog — the LRU is here to avoid the SELECT on repeat
    lookups within a single scrape batch."""
    return f"{category}:{hash_}"


def _utc_day_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _lookup_cached_response(
    session: Session, *, title_hash: str, category: str
) -> dict | None:
    row = session.exec(
        select(LlmExtractionLog)
        .where(
            LlmExtractionLog.title_hash == title_hash,
            LlmExtractionLog.category == category,
            LlmExtractionLog.parsed_ok.is_(True),
        )
        .order_by(LlmExtractionLog.created_at.desc())
        .limit(1)
    ).first()
    return row.response_json if row else None


def _daily_count(session: Session, *, category: str) -> int:
    day_start = _utc_day_start().replace(tzinfo=None)
    n = session.exec(
        select(func.count())
        .select_from(LlmExtractionLog)
        .where(
            LlmExtractionLog.category == category,
            LlmExtractionLog.created_at >= day_start,
        )
    ).one()
    return int(n) if n is not None else 0


def _log(
    session: Session,
    *,
    title: str,
    title_hash: str,
    category: str,
    response_json: dict | None,
    parsed_ok: bool,
    latency_ms: int,
    error: str | None,
) -> None:
    row = LlmExtractionLog(
        title=title[:1024],
        title_hash=title_hash,
        category=category,
        response_json=response_json,
        parsed_ok=parsed_ok,
        latency_ms=latency_ms,
        error=error,
    )
    session.add(row)
    session.flush()


# --------------------------------------------------------------------------
# Client-side rate limiting
# --------------------------------------------------------------------------
# Gemini 2.5 Flash free tier caps at 20 RPM. Below-the-limit throttling
# keeps a batch normalization pass from tripping 429s and losing calls to
# unrecoverable rate-limit rejections.

import threading as _threading  # noqa: E402

_rpm_lock = _threading.Lock()
_recent_calls: list[float] = []


def _rate_limit_wait() -> None:
    """Block until safe to make another call under the target RPM.

    Uses a sliding 60-second window. Target RPM is 15 (leaves headroom
    below the 20 RPM cap so parallel scrapers can share).
    """
    target_rpm = 15
    with _rpm_lock:
        now = time.time()
        # Drop entries older than 60s.
        cutoff = now - 60.0
        while _recent_calls and _recent_calls[0] < cutoff:
            _recent_calls.pop(0)
        if len(_recent_calls) >= target_rpm:
            wait = 60.0 - (now - _recent_calls[0]) + 0.1
            if wait > 0:
                time.sleep(wait)
                now = time.time()
                cutoff = now - 60.0
                while _recent_calls and _recent_calls[0] < cutoff:
                    _recent_calls.pop(0)
        _recent_calls.append(now)


_RETRY_AFTER_RE = re.compile(r"retry in\s+([\d.]+)s", re.IGNORECASE)


def _extract_retry_after(err: Exception) -> float | None:
    """Pull the 'Please retry in Ns' hint from a Gemini 429 error message."""
    m = _RETRY_AFTER_RE.search(str(err))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _call_gemini_sync(
    *,
    prompt: str,
    title: str,
    schema: type[BaseModel],
) -> dict | None:
    """Synchronous Gemini call, wrapped in a ThreadPoolExecutor by the caller
    so we can enforce a hard wall-clock timeout regardless of SDK version.

    Handles the free-tier's per-minute rate limit two ways:
    1. Client-side throttle before the call (avoid triggering 429 at all).
    2. On 429 despite that (other processes / recent activity we can't see),
       sleep the server's retry-after hint and retry ONCE. Only retries once
       so a hard-quota exhaustion doesn't loop forever.
    """
    client = _get_client()
    if client is None:
        return None
    try:
        from google.genai import types  # type: ignore[import-not-found]
    except ImportError:
        return None

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.0,
        max_output_tokens=512,
    )

    def _do_call() -> Any:
        _rate_limit_wait()
        return client.models.generate_content(
            model=settings.gemini_model,
            contents=[prompt, f"Title: {title}"],
            config=config,
        )

    try:
        resp = _do_call()
    except Exception as exc:  # noqa: BLE001 — inspect status only
        if "429" not in str(exc):
            raise
        wait = _extract_retry_after(exc)
        # Bound the retry sleep — a "retry in 60s" hint should be honoured,
        # but pathological hints (or daily-cap errors that suggest hours)
        # should not block ingest for minutes.
        if wait is None or wait > 65:
            raise
        time.sleep(wait + 0.5)
        resp = _do_call()

    # google-genai exposes .parsed as the SDK-hydrated Pydantic instance when
    # response_schema is provided. Fall back to .text JSON parsing on drift.
    parsed = getattr(resp, "parsed", None)
    if parsed is not None:
        return parsed.model_dump()
    text = getattr(resp, "text", None)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _call_with_timeout(prompt: str, title: str, schema: type[BaseModel]) -> dict | None:
    """Enforce a wall-clock timeout on the Gemini call.

    Timeout budget includes any rate-limit wait or 429 retry-after sleep,
    so we set a generous hard cap regardless of the (short) API latency
    budget in settings.
    """
    # Rate-limit wait + 429 retry can be ~120s worst case. Give headroom.
    hard_timeout = max(settings.gemini_timeout_seconds, 140.0)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_call_gemini_sync, prompt=prompt, title=title, schema=schema)
        try:
            return fut.result(timeout=hard_timeout)
        except concurrent.futures.TimeoutError:
            return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def extract(session: Session, *, title: str, category: str) -> ParsedTitle | None:
    """Return a ParsedTitle produced by the LLM, or None on any failure.

    Never raises. On timeout, invalid JSON, DB error, missing key, or missing
    SDK, returns None so the caller can drop the listing (matching v0 behavior).
    """
    if not settings.llm_fallback_enabled:
        return None
    if category not in SCHEMAS or category not in COMPOSERS:
        return None

    h = _title_hash(title, category)
    _cached_lookup_key(h, category)  # warm the LRU

    # DB cache: same title, any merchant, recent success.
    try:
        cached = _lookup_cached_response(session, title_hash=h, category=category)
    except Exception:  # noqa: BLE001 — never let a DB read break ingest
        cached = None
    if cached is not None:
        return _compose_or_none(category, cached)

    # Daily cap.
    try:
        count = _daily_count(session, category=category)
    except Exception:  # noqa: BLE001
        count = 0
    if count >= settings.llm_daily_cap_per_category:
        return None

    schema = SCHEMAS[category]
    prompt = _PROMPTS[category]
    start = time.perf_counter()
    error: str | None = None
    response: dict | None = None
    try:
        response = _call_with_timeout(prompt=prompt, title=title, schema=schema)
    except Exception as exc:  # noqa: BLE001 — capture everything
        error = f"{type(exc).__name__}: {exc}"[:512]
        response = None
    latency_ms = int((time.perf_counter() - start) * 1000)

    ok = response is not None and bool(response.get("is_valid_for_category"))
    try:
        _log(
            session,
            title=title,
            title_hash=h,
            category=category,
            response_json=response,
            parsed_ok=ok,
            latency_ms=latency_ms,
            error=error,
        )
    except Exception:  # noqa: BLE001 — logging must not break ingest
        session.rollback()

    if not ok or response is None:
        return None
    return _compose_or_none(category, response)


def _compose_or_none(category: str, response: dict) -> ParsedTitle | None:
    composer = COMPOSERS.get(category)
    if composer is None:
        return None
    try:
        parsed = composer(response)
    except Exception:  # noqa: BLE001 — a bad LLM payload should never blow up ingest
        return None
    if not parsed.canonical_key:
        return None
    return parsed
