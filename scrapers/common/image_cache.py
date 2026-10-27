"""Copy a merchant's product image into our own object storage.

Every image on this site is currently a hotlink, so we inherit each
merchant's uptime, bot posture and file hygiene. That is what emptied page
one of /c/phones (OPERATIONS.md 8ag): phoneplacekenya.com put the whole
origin behind a Cloudflare managed challenge, which an <img> request can
never solve because there is no JS context to solve it in. Caching our own
copy is the only fix that does not depend on a merchant's goodwill.

Content-addressed: the key is the SHA-256 of the bytes, so the same photo
served by six merchants is stored once, and re-running the backfill
rewrites nothing. Nothing here mutates the DB — callers decide what to do
with the returned URL.

Storage is S3-compatible (Cloudflare R2 via boto3). Disabled and inert
unless all four R2 settings are present, so dev and CI need no credentials.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

import httpx

from app.config import settings

# Formats a browser will actually render, mapped to the extension we store
# under. Anything else (SVG, HTML error pages dressed as images, PDFs) is
# refused — an <img> that silently fails is the bug we are fixing.
_ALLOWED: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
}

# Magic bytes, checked instead of trusting Content-Type. A blocked merchant
# commonly returns an HTML challenge page with a 200 and an image/* header;
# storing that would cache the outage.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)

# Big enough for any product photo a merchant publishes, small enough that a
# mis-pointed URL can't stream us a video.
MAX_BYTES = 8 * 1024 * 1024
# Below this it is a tracking pixel or a placeholder, not a product photo.
MIN_BYTES = 1024


def cache_enabled() -> bool:
    return all(
        (
            settings.r2_account_id,
            settings.r2_access_key_id,
            settings.r2_secret_access_key,
            settings.r2_bucket,
        )
    )


def _sniff_ext(body: bytes, content_type: str) -> str | None:
    """Extension for `body`, or None when it is not a renderable image."""
    for magic, ext in _MAGIC:
        if body.startswith(magic):
            return ext
    # WebP and AVIF are RIFF/ISO-BMFF containers; check the brand, not a
    # fixed prefix. Both are common on the merchants we scrape.
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "webp"
    if body[4:8] == b"ftyp" and b"avif" in body[8:20]:
        return "avif"
    # Before trusting the header at all, rule out the bodies that lie. A
    # blocked merchant answers with 200, `Content-Type: image/*` and an HTML
    # challenge page; without this the header fallback below would accept it
    # and freeze a recoverable outage into our own bucket, where no later
    # scrape could ever repair it. Caught by
    # test_cloudflare_challenge_page_is_refused_despite_image_content_type.
    head = body[:512].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith((b"<!doctype", b"<html", b"<?xml", b"<svg", b"{", b"[")):
        return None

    # Only now fall back to the declared type, and only if it is one we allow.
    # Still needed: some CDNs serve AVIF/WebP variants whose containers we
    # have no magic for.
    return _ALLOWED.get(content_type.split(";")[0].strip().lower())


@lru_cache(maxsize=1)
def _client():
    """Lazily built S3 client. boto3 is a scraper-side dependency, so the
    web app never imports it."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        region_name="auto",
    )


def public_url(key: str) -> str:
    base = (settings.r2_public_base_url or "").rstrip("/")
    return f"{base}/{key}"


def _already_there(key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        _client().head_object(Bucket=settings.r2_bucket, Key=key)
        return True
    except ClientError:
        return False


async def fetch_bytes(url: str, *, client: httpx.AsyncClient) -> tuple[bytes, str] | None:
    """Download `url`, returning (body, ext) when it is a usable image.

    Returns None rather than raising for every failure mode — a merchant
    being down must not take a scrape leg with it.
    """
    try:
        resp = await client.get(url, follow_redirects=True, timeout=25.0)
    except Exception:  # noqa: BLE001 — network, DNS, TLS, timeout
        return None
    if resp.status_code != 200:
        return None
    body = resp.content
    if not (MIN_BYTES <= len(body) <= MAX_BYTES):
        return None
    ext = _sniff_ext(body, resp.headers.get("content-type", ""))
    return (body, ext) if ext else None


def store(body: bytes, ext: str) -> str:
    """PUT `body` under its content hash; return the public URL.

    Skips the upload when the key already exists, which is what makes the
    backfill cheap to re-run and makes six merchants sharing one photo cost
    one object.
    """
    key = f"p/{hashlib.sha256(body).hexdigest()[:32]}.{ext}"
    if not _already_there(key):
        _client().put_object(
            Bucket=settings.r2_bucket,
            Key=key,
            Body=body,
            ContentType=next(
                (ct for ct, e in _ALLOWED.items() if e == ext), "application/octet-stream"
            ),
            # Immutable by construction: the key IS the hash, so a given key
            # can never have different bytes. Let Cloudflare keep it forever.
            CacheControl="public, max-age=31536000, immutable",
        )
    return public_url(key)


async def cache_image(url: str, *, client: httpx.AsyncClient) -> str | None:
    """Full path: download, validate, store. None when any step says no."""
    if not cache_enabled():
        return None
    got = await fetch_bytes(url, client=client)
    if not got:
        return None
    body, ext = got
    return store(body, ext)
