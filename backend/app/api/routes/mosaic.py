from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import session_from_request
from app.domain.job_schemas import JobResource, MosaicJobCreate
from app.services.job_service import JobService


router = APIRouter(prefix="/tasks/{task_id}/mosaic-jobs", tags=["mosaic"])


@router.post("", response_model=JobResource, status_code=status.HTTP_202_ACCEPTED)
def create_mosaic_job(
    task_id: str,
    data: MosaicJobCreate,
    request: Request,
    response: Response,
    session: Session = Depends(session_from_request),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobResource:
    resource, created = JobService(
        session, request.app.state.settings
    ).create_mosaic(task_id, data, idempotency_key)
    response.headers["Location"] = resource.links.self
    if not created:
        response.headers["Idempotency-Replayed"] = "true"
    return resource

