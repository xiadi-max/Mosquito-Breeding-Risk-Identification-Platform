from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def migrate_database(settings: Settings) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = settings.resolved_database_url
    command.upgrade(config, "head")


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    database_path = tmp_path / "mosquito_mapper_test.sqlite3"
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        storage_root=tmp_path / "artifacts",
        cors_origins="http://testserver",
        mosaic_provider="fake",
        detector_provider="fake",
        decision_provider="rules",
    )


@pytest.fixture
def client(test_settings: Settings):
    app = create_app(test_settings)
    with TestClient(app) as active_client:
        yield active_client


@pytest.fixture
def migrated_client(test_settings: Settings):
    migrate_database(test_settings)
    app = create_app(test_settings)
    with TestClient(app) as active_client:
        yield active_client
