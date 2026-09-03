from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.middleware import RequestContextMiddleware
from app.api.router import api_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.frontend import router as frontend_router
from app.core.config import Settings, get_settings
from app.core.db import create_db_engine, create_session_factory
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)
    engine = create_db_engine(active_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        active_settings.resolved_storage_root.mkdir(parents=True, exist_ok=True)
        logger.info(
            "api started",
            extra={
                "environment": active_settings.app_env,
                "mosaic_provider": active_settings.mosaic_provider,
                "detector_provider": active_settings.detector_provider,
                "decision_provider": active_settings.decision_provider,
            },
        )
        try:
            yield
        finally:
            engine.dispose()
            logger.info("api stopped")

    app = FastAPI(
        title="MosquitoMapper Backend API",
        summary="Mosquito surveillance image processing and risk analysis API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    install_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "ETag", "Content-Disposition"],
    )
    # Add request context last so it wraps CORS-generated preflight responses too.
    app.add_middleware(RequestContextMiddleware)
    app.include_router(api_router)
    app.include_router(dashboard_router)
    app.include_router(frontend_router)
    return app


app = create_app()
