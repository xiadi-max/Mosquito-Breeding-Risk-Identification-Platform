from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select

from app.core.db import create_db_engine, create_session_factory, get_schema_revision
from app.domain.models import WorkerHeartbeat
from app.worker import run_worker


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _upgrade(settings) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = settings.resolved_database_url
    command.upgrade(config, "head")


@pytest.mark.integration
def test_initial_migration_creates_worker_heartbeat_table(test_settings) -> None:
    _upgrade(test_settings)
    engine = create_db_engine(test_settings)
    try:
        assert "worker_heartbeats" in inspect(engine).get_table_names()
        assert get_schema_revision(engine) == "20260824_0007"
    finally:
        engine.dispose()


@pytest.mark.integration
def test_alembic_metadata_matches_m5_head(test_settings) -> None:
    _upgrade(test_settings)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = test_settings.resolved_database_url
    command.check(config)


@pytest.mark.integration
def test_worker_once_persists_heartbeat(test_settings) -> None:
    _upgrade(test_settings)

    assert run_worker(once=True, settings=test_settings) == 0

    engine = create_db_engine(test_settings)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            heartbeat = session.execute(select(WorkerHeartbeat)).scalar_one()
            assert heartbeat.status == "stopping"
            assert heartbeat.process_id > 0
    finally:
        engine.dispose()
