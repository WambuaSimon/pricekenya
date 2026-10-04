from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_kwargs: dict = {"echo": False, "connect_args": connect_args}
# Postgres (Render) only: a real connection pool.
#
# Render ships no built-in pooler — the platform's own guidance is that
# pooling is the application's job — so this QueuePool *is* the pooling
# layer. There is no PgBouncer behind it to absorb anything.
#
# This replaced NullPool, which existed solely so Neon's compute could scale
# to zero: a pool holding sockets open kept the endpoint awake and billable.
# Measured over 44.6 days on Neon, that bought 2.45 hours of suspend time —
# 0.23%, across 91 wake cycles with a median nap of 59 seconds. ~500
# pageviews/day plus Googlebot plus two scrape bursts never left a 5-minute
# idle gap, so the endpoint was effectively always on and billed at the 0.25
# CU floor anyway, while every single request paid a fresh connect, TLS
# handshake and full Postgres backend startup. Render's compute is always on
# and billed flat, so warm connections cost nothing and save that setup.
#
# pool_pre_ping and pool_recycle are load-bearing again. Under NullPool they
# were inert (every connection was new by construction); here they discard a
# socket the far side already dropped, at checkout, rather than letting it
# surface as a 500.
#
# Sizing: one web instance, one uvicorn worker, so 5 + 5 overflow = 10
# connections from the app. Scrape legs run at max-parallel 5 as separate
# processes, each single-threaded, so 1-2 connections each. Comfortably
# inside the ~100-connection ceiling Render gives sub-8GB plans.
if not settings.database_url.startswith("sqlite"):
    engine_kwargs.update(
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=1800,
    )
engine = create_engine(settings.database_url, **engine_kwargs)


def init_db() -> None:
    from db import models  # noqa: F401  - register models with SQLModel metadata

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
