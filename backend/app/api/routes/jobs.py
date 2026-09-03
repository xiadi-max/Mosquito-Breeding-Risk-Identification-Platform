from __future__ import annotations

import json
import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import session_from_request
from app.api.sse import ServerSentEvent
from app.core.errors import AppError
from app.domain.enums import JobStatus
from app.domain.job_schemas import JobResource
from app.repositories.job_repository import JobRepository
from app.services.job_service import JobService, job_to_read


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResource)
def get_job(
    job_id: str,
    request: Request,
    session: Session = Depends(session_from_request),
) -> JobResource:
    return JobService(session, request.app.state.settings).get(job_id)


@router.post("/{job_id}/cancel", response_model=JobResource)
def cancel_job(
    job_id: str,
    request: Request,
    session: Session = Depends(session_from_request),
) -> JobResource:
    return JobService(session, request.app.state.settings).cancel(job_id)


def _event_stream(
    *,
    factory,
    settings,
    job_id: str,
    last_event_id: int | None,
) -> Iterator[str]:
    cursor = last_event_id or 0
    with factory() as session:
        service = JobService(session, settings)
        job = service.get_model(job_id)
        snapshot = job_to_read(job).model_dump(mode="json")
    yield ServerSentEvent(event="snapshot", data=snapshot).encode()

    last_heartbeat = time.monotonic()
    while True:
        with factory() as session:
            repository = JobRepository(session)
            job = repository.get(job_id)
            if job is None:
                return
            events = repository.events_after(job_id, cursor)
            status_value = JobStatus(job.status)
        for event in events:
            try:
                data = json.loads(event.data_json)
            except json.JSONDecodeError:
                data = {"job_id": job_id, "invalid_event_data": True}
            yield ServerSentEvent(
                event=event.event_type,
                data=data,
                event_id=event.id,
            ).encode()
            cursor = event.id

        if status_value.terminal and not events:
            return
        if time.monotonic() - last_heartbeat >= settings.sse_heartbeat_seconds:
            yield ServerSentEvent(
                event="heartbeat",
                data={"job_id": job_id, "timestamp": time.time()},
            ).encode()
            last_heartbeat = time.monotonic()
        time.sleep(min(settings.job_poll_interval, 1.0))


@router.get("/{job_id}/events")
def job_events(
    job_id: str,
    request: Request,
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    last_event_id = None
    if last_event_id_header is not None:
        try:
            last_event_id = int(last_event_id_header)
            if last_event_id < 0:
                raise ValueError
        except ValueError as exc:
            raise AppError(
                status_code=422,
                code="VALIDATION_ERROR",
                title="SSE 事件编号无效",
                detail="Last-Event-ID 必须是非负整数。",
            ) from exc

    # Validate before returning a streaming response so a missing job is problem+json.
    with request.app.state.session_factory() as session:
        JobService(session, request.app.state.settings).get_model(job_id)

    return StreamingResponse(
        _event_stream(
            factory=request.app.state.session_factory,
            settings=request.app.state.settings,
            job_id=job_id,
            last_event_id=last_event_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

