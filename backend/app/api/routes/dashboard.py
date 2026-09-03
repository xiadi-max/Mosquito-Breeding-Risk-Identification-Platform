from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import session_from_request
from app.domain.dashboard_schemas import DashboardResponse
from app.services.dashboard_service import DashboardService


router = APIRouter(prefix="/api/mosquito-workbench", tags=["compatibility"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    request: Request,
    task_id: str | None = Query(default=None),
    session: Session = Depends(session_from_request),
) -> DashboardResponse:
    return DashboardService(session, request.app.state.settings).get(task_id)

