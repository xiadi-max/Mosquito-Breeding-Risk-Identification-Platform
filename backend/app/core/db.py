from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    url = settings.resolved_database_url
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )

    if url.startswith("sqlite"):
        _configure_sqlite(engine)
    return engine


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()


def check_database_writable(engine: Engine) -> None:
    """Acquire a write transaction without persisting a probe record."""

    if engine.url.get_backend_name() == "sqlite":
        raw_connection = engine.raw_connection()
        try:
            cursor = raw_connection.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("SELECT 1")
                raw_connection.rollback()
            finally:
                cursor.close()
        finally:
            raw_connection.close()
        return

    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("SELECT 1"))
        transaction.rollback()


def get_schema_revision(engine: Engine) -> str | None:
    try:
        with engine.connect() as connection:
            return connection.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar_one_or_none()
    except SQLAlchemyError:
        return None


def get_worker_last_seen_at(engine: Engine) -> datetime | None:
    try:
        with engine.connect() as connection:
            value = connection.execute(
                text("SELECT MAX(last_seen_at) FROM worker_heartbeats")
            ).scalar_one_or_none()
    except SQLAlchemyError:
        return None

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def connection_info(connection: Connection) -> dict[str, str]:
    return {"dialect": connection.dialect.name}

