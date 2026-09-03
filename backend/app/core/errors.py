from __future__ import annotations

import logging
from collections.abc import Iterable
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)
PROBLEM_BASE = "https://mosquito-mapper.local/problems"


class AppError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        title: str,
        detail: str,
        errors: Iterable[dict[str, str | None]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = list(errors or [])


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _problem_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    title: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    slug = code.lower().replace("_", "-")
    payload = {
        "type": f"{PROBLEM_BASE}/{slug}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
        "code": code,
        "request_id": _request_id(request),
        "errors": errors or [],
    }
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _problem_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        errors=exc.errors,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc", ()))
        errors.append({"field": location or None, "message": item.get("msg", "invalid")})
    return _problem_response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        title="请求参数校验失败",
        detail="请求中的一个或多个字段不符合接口要求。",
        errors=errors,
    )


async def http_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    try:
        title = HTTPStatus(exc.status_code).phrase
    except ValueError:
        title = "HTTP Error"
    detail = exc.detail if isinstance(exc.detail, str) else title
    code = "NOT_FOUND" if exc.status_code == 404 else f"HTTP_{exc.status_code}"
    response = _problem_response(
        request,
        status_code=exc.status_code,
        code=code,
        title=title,
        detail=detail,
    )
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled request error",
        extra={"request_id": _request_id(request), "error_code": "INTERNAL_ERROR"},
    )
    return _problem_response(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        title="服务器内部错误",
        detail="服务器处理请求时发生未预期错误。",
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)
