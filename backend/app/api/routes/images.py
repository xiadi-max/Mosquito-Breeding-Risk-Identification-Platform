from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import session_from_request
from app.domain.image_schemas import ImageList, ImageUploadResponse
from app.services.upload_service import UploadService


router = APIRouter(prefix="/tasks/{task_id}/images", tags=["images"])


@router.get("", response_model=ImageList)
def list_images(
    task_id: str,
    request: Request,
    session: Session = Depends(session_from_request),
) -> ImageList:
    items, summary = UploadService(session, request.app.state.settings).list(task_id)
    return ImageList(items=items, next_cursor=None, summary=summary)


@router.post(
    "",
    response_model=ImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_images(
    task_id: str,
    request: Request,
    files: Annotated[list[UploadFile], File(description="JPG, JPEG, or PNG images")],
    session: Session = Depends(session_from_request),
) -> ImageUploadResponse:
    return await UploadService(session, request.app.state.settings).upload(task_id, files)


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    task_id: str,
    image_id: str,
    request: Request,
    session: Session = Depends(session_from_request),
) -> Response:
    UploadService(session, request.app.state.settings).delete(task_id, image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
