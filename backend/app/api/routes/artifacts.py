from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import session_from_request
from app.services.artifact_service import ArtifactService


router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}/content", response_class=Response)
def artifact_content(
    artifact_id: str,
    request: Request,
    session: Session = Depends(session_from_request),
) -> Response:
    return ArtifactService(session, request.app.state.settings).content(
        artifact_id, request
    )

