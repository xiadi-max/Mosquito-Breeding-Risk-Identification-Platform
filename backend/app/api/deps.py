from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def settings_from_request(request: Request) -> Settings:
    return request.app.state.settings


def engine_from_request(request: Request) -> Engine:
    return request.app.state.engine


def session_from_request(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    session = factory()
    try:
        yield session
    finally:
        session.close()

