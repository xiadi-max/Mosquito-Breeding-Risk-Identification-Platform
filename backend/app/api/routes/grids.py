from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import session_from_request
from app.domain.grid_schemas import GridParameters, GridPlanCreate, GridPlanRead, GridPreview
from app.domain.job_schemas import JobResource
from app.services.grid_service import GridService


router = APIRouter(prefix="/tasks/{task_id}", tags=["grids"])


@router.post("/grid-plans/preview", response_model=GridPreview)
def preview_grid(
    task_id: str,
    data: GridParameters,
    request: Request,
    session: Session = Depends(session_from_request),
) -> GridPreview:
    return GridService(session, request.app.state.settings).preview(task_id, data)


@router.put(
    "/grid-plan",
    response_model=JobResource,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_grid_plan(
    task_id: str,
    data: GridPlanCreate,
    request: Request,
    response: Response,
    session: Session = Depends(session_from_request),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobResource:
    resource, created = GridService(
        session, request.app.state.settings
    ).create_job(task_id, data, idempotency_key)
    response.headers["Location"] = resource.links.self
    if not created:
        response.headers["Idempotency-Replayed"] = "true"
    return resource


@router.get("/grid-plan", response_model=GridPlanRead)
def get_grid_plan(
    task_id: str,
    request: Request,
    session: Session = Depends(session_from_request),
) -> GridPlanRead:
    return GridService(session, request.app.state.settings).get_current(task_id)

