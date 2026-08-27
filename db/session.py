from collections.abc import Iterator

from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_kwargs: dict = {"echo": False, "connect_args": connect_args}
# Postgres (Neon) only: NullPool, so a connection is opened per checkout and
# closed on release rather than parked in a pool.
#
# This is a billing decision as much as a correctness one. Neon scales the
# compute to zero once the endpoint goes idle, and it cannot do that while a
# client holds sockets open. SQLAlchemy's default QueuePool keeps up to five
# connections alive for the life of the process, so the endpoint effectively
# never slept: 158 CU-hrs over 26 days is 6.1/day, and 0.25 CU pinned for a
# full 24h is 6.0/day. The only suspend windows visible on the Neon graph
# lined up with Render restarts dropping the pool.
#
# The previous settings here did not address that, despite a comment saying
# they did. pool_recycle never proactively closes an idle connection; it only
# discards one that is already too old AT CHECKOUT, which prevents the stale-
# socket error but keeps the socket open in the meantime. pool_pre_ping is
# likewise checkout-time only. Both are redundant under NullPool, where every
# connection is new by construction, so they are gone rather than left to
# imply a pooling strategy that is no longer in play.
#
# Cost of the trade: a connect + TLS handshake per checkout. Point
# DATABASE_URL at Neon's `-pooler` host so PgBouncer absorbs that; the direct
# `ep-*` host makes every request pay full Postgres backend startup.
if not settings.database_url.startswith("sqlite"):
    engine_kwargs["poolclass"] = NullPool
engine = create_engine(settings.database_url, **engine_kwargs)


def init_db() -> None:
    from db import models  # noqa: F401  - register models with SQLModel metadata

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
