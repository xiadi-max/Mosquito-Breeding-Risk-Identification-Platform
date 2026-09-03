from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response


router = APIRouter(tags=["frontend"])
FRONTEND_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_ASSETS = {
    "index.html": "index.html",
    "data.js": "data.js",
    "test_data.js": "test_data.js",
    "api-client.js": "api-client.js",
    "api-integration.js": "api-integration.js",
}


def _file(name: str) -> FileResponse:
    path = FRONTEND_ROOT / PUBLIC_ASSETS[name]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="frontend asset not found")
    media_type = "text/html" if path.suffix == ".html" else "text/javascript"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache"})


@router.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    return _file("index.html")


@router.get("/frontend-config.js", include_in_schema=False)
def frontend_config(request: Request) -> Response:
    payload = {
        "apiBaseUrl": "/api/v1",
        "dashboardUrl": "/api/mosquito-workbench/dashboard",
        "demoAllowed": request.app.state.settings.app_env != "production",
        "environment": request.app.state.settings.app_env,
    }
    body = "window.RUNTIME_CONFIG = " + json.dumps(payload, ensure_ascii=False) + ";"
    return Response(body, media_type="text/javascript", headers={"Cache-Control": "no-store"})


@router.get("/{asset_name}", include_in_schema=False)
def frontend_asset(asset_name: str, request: Request) -> FileResponse:
    if asset_name not in PUBLIC_ASSETS:
        raise HTTPException(status_code=404, detail="frontend asset not found")
    if asset_name == "test_data.js" and request.app.state.settings.production_mode:
        raise HTTPException(status_code=404, detail="demo data is disabled")
    return _file(asset_name)
