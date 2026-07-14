from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_kwargs: dict = {"echo": False, "connect_args": connect_args}
# Postgres (Neon) only: pool_pre_ping validates each checkout with a
# lightweight SELECT 1, so stale sockets dropped by Neon's free-tier
# idle-suspend get transparently replaced instead of raising
# OperationalError to the request handler. pool_recycle=280 pre-empts
# Neon's ~300s idle window so we never hand out a connection that's
# about to be closed server-side. Sqlite has neither concept.
if not settings.database_url.startswith("sqlite"):
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 280
engine = create_engine(settings.database_url, **engine_kwargs)


def init_db() -> None:
    from db import models  # noqa: F401  - register models with SQLModel metadata

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
