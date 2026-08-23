"""Rebuild the cached sitemap out-of-band, off the request path.

`GET /sitemap.xml` is cache-first: it serves `CachedSitemap(id=1)` until
that row is older than `_SITEMAP_CACHE_TTL_HOURS`, then the *next request
in the window* pays the full build — a GROUP BY over every Listing joined
to every Product, serialized into ~1MB of XML. Two problems with letting
that happen lazily:

  1. Whoever eats the rebuild is usually Googlebot, since it hits
     /sitemap.xml more reliably than humans do. On a 0.5-CPU Render dyno
     the build can approach Cloudflare's 100s origin timeout — a 524 shows
     up in Search Console as "sitemap could not be read".
  2. There is no lock. Every request arriving in the window after the TTL
     lapses runs its own build and they all race to write id=1, which is
     row-lock contention on the write path of a live web request.

Running this from CI on a schedule keeps the cached row fresher than the
TTL, so the lazy path in `app/routes/meta.py` degrades into a safety net
that should never actually fire in production.

Rebuild is unconditional — that's the point of calling it deliberately.
Use `--if-older-than N` to make it a no-op when the row is still fresh
(handy for a manual run you don't want to pay for).

Usage:
    python -m scripts.rebuild_sitemap
    python -m scripts.rebuild_sitemap --if-older-than 6
    python -m scripts.rebuild_sitemap --dry-run   # build + report, no write
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlmodel import Session

from app.config import settings
from app.routes.meta import _build_sitemap_xml
from db.models import CachedSitemap
from db.session import engine


class UnsafeBaseUrl(RuntimeError):
    """Raised when BASE_URL isn't a production host — see _assert_safe_base_url."""


def _assert_safe_base_url(base_url: str) -> None:
    """Refuse to publish a sitemap built from a non-production BASE_URL.

    Learned the hard way on 2026-08-22: this script was run from a laptop
    without BASE_URL set, inherited `http://localhost:8000` from the local
    .env, and published 1,377 localhost URLs to the production sitemap. It
    was live for about a minute. Nothing failed — every layer did exactly
    what it was told.

    The workflow always passes BASE_URL explicitly so it was never at risk;
    this guard exists for the manual run, which is precisely the case with
    no review step. `--dry-run` skips it, so you can still inspect a build
    locally.
    """
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise UnsafeBaseUrl(
            f"BASE_URL is {base_url!r} — refusing to write a sitemap that "
            f"isn't https. Re-run with BASE_URL set to the production host, "
            f"or pass --dry-run to build without writing."
        )
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        raise UnsafeBaseUrl(
            f"BASE_URL is {base_url!r} — that's a local host. Publishing it "
            f"would put dev URLs in the production sitemap. Re-run with "
            f"BASE_URL set to the production host, or pass --dry-run."
        )


def rebuild(session: Session, *, if_older_than: float | None = None, dry_run: bool = False) -> int:
    """Rebuild CachedSitemap(id=1). Returns the URL count written.

    Returns the existing row's `url_count` unchanged when `if_older_than`
    is set and the row is still within that many hours.
    """
    # Check before doing any work — a bad BASE_URL makes the whole build
    # worthless, so fail on the first line rather than after the GROUP BY.
    if not dry_run:
        _assert_safe_base_url(settings.base_url)

    # `generated_at` is written with utcnow() by the route, so stay in the
    # same naive-UTC frame — an aware datetime here would raise on the
    # subtraction below. This is the non-deprecated spelling of utcnow().
    now = datetime.now(UTC).replace(tzinfo=None)
    cached = session.get(CachedSitemap, 1)

    if if_older_than is not None and cached is not None:
        age_hours = (now - cached.generated_at).total_seconds() / 3600.0
        if age_hours < if_older_than:
            print(
                f"[sitemap] cached row is {age_hours:.1f}h old "
                f"(< {if_older_than:g}h) — skipping rebuild."
            )
            return cached.url_count

    prior_count = cached.url_count if cached else 0
    body, url_count = _build_sitemap_xml(session)

    if dry_run:
        print(f"[sitemap] dry run: would write {url_count} URLs ({len(body):,} bytes).")
        return url_count

    if cached:
        cached.body = body
        cached.generated_at = now
        cached.url_count = url_count
        session.add(cached)
    else:
        session.add(
            CachedSitemap(id=1, body=body, generated_at=now, url_count=url_count)
        )
    session.commit()

    delta = url_count - prior_count
    print(
        f"[sitemap] rebuilt: {url_count} URLs ({len(body):,} bytes), "
        f"{delta:+d} vs previous {prior_count}."
    )
    return url_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild the cached sitemap XML row (CachedSitemap id=1)."
    )
    parser.add_argument(
        "--if-older-than",
        type=float,
        default=None,
        metavar="HOURS",
        help="Skip the rebuild when the cached row is younger than this.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and report the URL count without writing to the DB.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        try:
            rebuild(session, if_older_than=args.if_older_than, dry_run=args.dry_run)
        except UnsafeBaseUrl as exc:
            # Exit non-zero with a readable one-liner rather than a traceback:
            # in CI this is what shows up in the Telegram-notified job log.
            raise SystemExit(f"[sitemap] refusing to publish — {exc}") from None


if __name__ == "__main__":
    main()
