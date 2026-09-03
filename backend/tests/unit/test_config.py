from pathlib import Path

from app.core.config import Settings


def test_relative_runtime_paths_are_resolved_from_backend_root() -> None:
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///./data/unit.sqlite3",
        storage_root=Path("./data/artifacts"),
    )

    assert settings.resolved_database_url.endswith("/data/unit.sqlite3")
    assert settings.resolved_storage_root == settings.backend_root / "data" / "artifacts"


def test_cors_origins_accept_comma_separated_and_json_values() -> None:
    comma = Settings(_env_file=None, cors_origins="https://a.example, https://b.example")
    as_json = Settings(_env_file=None, cors_origins='["https://a.example"]')

    assert comma.cors_origin_list == ["https://a.example", "https://b.example"]
    assert as_json.cors_origin_list == ["https://a.example"]

