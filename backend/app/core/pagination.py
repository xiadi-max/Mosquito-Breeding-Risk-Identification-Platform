from __future__ import annotations

import base64
import json
from datetime import datetime

from app.core.errors import AppError
from app.core.time import ensure_utc


def encode_cursor(timestamp: datetime, entity_id: str) -> str:
    payload = json.dumps(
        [ensure_utc(timestamp).isoformat(), entity_id],
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        timestamp_text, entity_id = json.loads(raw.decode("utf-8"))
        timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError
        return ensure_utc(timestamp), entity_id
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            title="分页游标无效",
            detail="cursor 不是服务器生成的有效分页游标。",
            errors=[{"field": "cursor", "message": "invalid cursor"}],
        ) from exc

