from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import session_from_request
from app.domain.task_schemas import TaskCreate, TaskDetail, TaskList, TaskUpdate
from app.services.task_service import TaskService, parse_expected_version


router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskList)
def list_tasks(
    q: str | None = Query(default=None, min_length=1, max_length=120),
    state_filter: Literal["running", "done", "archived"] | None = Query(
        default=None, alias="state"
    ),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=1000),
    session: Session = Depends(session_from_request),
) -> TaskList:
    return TaskService(session).list(
        q=q,
        state=state_filter,
        limit=limit,
        cursor=cursor,
    )


@router.post("", response_model=TaskDetail, status_code=status.HTTP_201_CREATED)
def create_task(
    data: TaskCreate,
    response: Response,
    session: Session = Depends(session_from_request),
) -> TaskDetail:
    task = TaskService(session).create(data)
    response.headers["Location"] = f"/api/v1/tasks/{task.id}"
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(
    task_id: str,
    response: Response,
    session: Session = Depends(session_from_request),
) -> TaskDetail:
    task = TaskService(session).get(task_id)
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.patch("/{task_id}", response_model=TaskDetail)
def update_task(
    task_id: str,
    data: TaskUpdate,
    response: Response,
    session: Session = Depends(session_from_request),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> TaskDetail:
    expected_version = parse_expected_version(if_match, data.expected_version)
    task = TaskService(session).update(task_id, data, expected_version)
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.post("/{task_id}/archive", response_model=TaskDetail)
def archive_task(
    task_id: str,
    response: Response,
    session: Session = Depends(session_from_request),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> TaskDetail:
    expected_version = parse_expected_version(if_match, None)
    task = TaskService(session).archive(task_id, expected_version)
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: str,
    request: Request,
    session: Session = Depends(session_from_request),
) -> Response:
    TaskService(session).delete(task_id, request.app.state.settings.resolved_storage_root)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
