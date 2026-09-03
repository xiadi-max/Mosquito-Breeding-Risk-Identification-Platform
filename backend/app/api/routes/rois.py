from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import session_from_request
from app.domain.roi_schemas import ROICollection, ROIReplace
from app.services.roi_service import ROIService


router = APIRouter(prefix="/tasks/{task_id}/rois", tags=["rois"])


@router.get("", response_model=ROICollection)
def get_rois(
    task_id: str,
    response: Response,
    session: Session = Depends(session_from_request),
) -> ROICollection:
    result = ROIService(session).get(task_id)
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.put("", response_model=ROICollection)
def replace_rois(
    task_id: str,
    data: ROIReplace,
    response: Response,
    session: Session = Depends(session_from_request),
) -> ROICollection:
    result = ROIService(session).replace(task_id, data)
    response.headers["ETag"] = f'"{result.version}"'
    return result

