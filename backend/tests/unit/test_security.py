from pathlib import Path

import pytest

from app.core.security import request_id_or_new, resolve_storage_path


def test_request_id_reuses_only_safe_header_value() -> None:
    assert request_id_or_new("client-123") == "client-123"
    generated = request_id_or_new("bad request id\n")
    assert generated.startswith("req_")


def test_storage_path_stays_below_root(tmp_path: Path) -> None:
    target = resolve_storage_path(tmp_path, "tasks/task-id/preview.jpg")
    assert target == tmp_path / "tasks" / "task-id" / "preview.jpg"


@pytest.mark.parametrize(
    "unsafe_path",
    ["../secret.txt", "/absolute/path", "tasks/../../secret.txt", ""],
)
def test_storage_path_rejects_traversal_and_invalid_targets(
    tmp_path: Path, unsafe_path: str
) -> None:
    with pytest.raises(ValueError):
        resolve_storage_path(tmp_path, unsafe_path)

