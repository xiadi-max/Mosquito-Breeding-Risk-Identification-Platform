from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from uuid import uuid4


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def request_id_or_new(value: str | None) -> str:
    if value and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return f"req_{uuid4().hex}"


def resolve_storage_path(storage_root: Path, relative_path: str) -> Path:
    """Resolve a database path while rejecting absolute paths and traversal."""

    posix_path = PurePosixPath(relative_path)
    if posix_path.is_absolute() or ".." in posix_path.parts:
        raise ValueError("unsafe artifact path")
    root = storage_root.resolve()
    target = root.joinpath(*posix_path.parts).resolve()
    if target == root or root not in target.parents:
        raise ValueError("artifact path escapes storage root")
    return target

