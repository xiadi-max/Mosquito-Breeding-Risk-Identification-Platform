from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import session_from_request
from app.domain.inference_schemas import DetectionList, InferenceJobCreate, ReviewResult, ReviewUpdate
from app.domain.job_schemas import JobResource
from app.services.inference_service import InferenceService
from app.services.review_service import ReviewService


router = APIRouter(prefix="/tasks/{task_id}", tags=["inference", "reviews"])


@router.post("/inference-jobs", response_model=JobResource, status_code=status.HTTP_202_ACCEPTED)
def create_inference_job(task_id: str, data: InferenceJobCreate, request: Request,
                         response: Response, session: Session = Depends(session_from_request),
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> JobResource:
    resource, created = InferenceService(session, request.app.state.settings).create_job(task_id, data, idempotency_key)
    response.headers["Location"] = resource.links.self
    if not created:
        response.headers["Idempotency-Replayed"] = "true"
    return resource


@router.get("/detections", response_model=DetectionList)
def detections(task_id: str, run_id: str | None = None, status_filter: str | None = Query(default=None, alias="status"),
               category: str | None = None, min_confidence: float = Query(default=0, ge=0, le=1),
               limit: int = Query(default=20, ge=1, le=100), cursor: str | None = None,
               session: Session = Depends(session_from_request)) -> DetectionList:
    return ReviewService(session).list_detections(task_id, run_id=run_id, status=status_filter,
        category=category, min_confidence=min_confidence, limit=limit, cursor=cursor)


@router.get("/reviews", response_model=DetectionList)
def reviews(task_id: str, status_filter: str = Query(default="pending", alias="status"),
            limit: int = Query(default=20, ge=1, le=100), cursor: str | None = None,
            session: Session = Depends(session_from_request)) -> DetectionList:
    return ReviewService(session).list_detections(task_id, run_id=None, status=status_filter,
        category=None, min_confidence=0, limit=limit, cursor=cursor)


@router.patch("/reviews/{detection_id}", response_model=ReviewResult)
def update_review(task_id: str, detection_id: str, data: ReviewUpdate,
                  session: Session = Depends(session_from_request)) -> ReviewResult:
    return ReviewService(session).update(task_id, detection_id, data)
