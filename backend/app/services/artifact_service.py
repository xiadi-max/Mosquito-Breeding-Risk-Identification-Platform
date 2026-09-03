from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import resolve_storage_path
from app.domain.enums import TaskState
from app.repositories.artifact_repository import ArtifactRepository


class ArtifactService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.repository = ArtifactRepository(session)
        self.settings = settings

    def content(self, artifact_id: str, request: Request) -> Response:
        artifact = self.repository.get(artifact_id)
        if artifact is None or artifact.task.state == TaskState.DELETING.value:
            self._not_found()
        path = resolve_storage_path(
            self.settings.resolved_storage_root, artifact.relative_path
        )
        if not path.is_file():
            self._not_found()

        etag = f'"{artifact.sha256}"'
        if_none_match = request.headers.get("if-none-match")
        if if_none_match in {etag, "*"}:
            return Response(status_code=304, headers={"ETag": etag})

        extension = Path(artifact.relative_path).suffix.lower()
        safe_filename = f"artifact-{artifact.id}{extension}"
        return FileResponse(
            path,
            media_type=artifact.mime_type,
            filename=safe_filename,
            # Image artifacts are application views (mosaic, crops and density
            # overlays), so browsers must be allowed to paint them in SVG/img.
            content_disposition_type=(
                "inline" if artifact.mime_type.startswith("image/") else "attachment"
            ),
            headers={
                "ETag": etag,
                "X-Content-Type-Options": "nosniff",
            },
        )

    @staticmethod
    def _not_found() -> None:
        raise AppError(
            status_code=404,
            code="ARTIFACT_NOT_FOUND",
            title="产物不存在",
            detail="产物不存在、已删除或不允许访问。",
        )
