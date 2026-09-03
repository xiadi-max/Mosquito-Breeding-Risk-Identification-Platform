from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ServerSentEvent:
    event: str
    data: dict[str, Any]
    event_id: int | None = None

    def encode(self) -> str:
        lines: list[str] = []
        if self.event_id is not None:
            lines.append(f"id: {self.event_id}")
        lines.append(f"event: {self.event}")
        lines.append(f"data: {json.dumps(self.data, ensure_ascii=False, separators=(',', ':'))}")
        return "\n".join(lines) + "\n\n"

