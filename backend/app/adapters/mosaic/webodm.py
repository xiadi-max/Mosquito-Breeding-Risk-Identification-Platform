from __future__ import annotations

import json
import mimetypes
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from PIL import Image

from app.adapters.mosaic.base import (
    MosaicCanceled,
    MosaicEngineError,
    MosaicExtraArtifact,
    MosaicResult,
    MosaicSource,
    raise_if_canceled,
)


TASK_STATUS = {
    10: "排队中",
    20: "处理中",
    30: "失败",
    40: "已完成",
    50: "已取消",
}


def webodm_configuration_ready(settings: Any) -> bool:
    url = str(settings.webodm_url or "").strip()
    parsed = urlparse(url)
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.netloc
        and str(settings.webodm_username or "").strip()
        and str(settings.webodm_password or "")
    )


class WebODMResponseError(RuntimeError):
    def __init__(self, code: str, detail: str, *, retryable: bool) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


class WebODMClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        verify_ssl: bool,
        request_timeout_seconds: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.request_timeout = (30, request_timeout_seconds)
        self.session = requests.Session()
        self._token: str | None = None
        self._token_lock = threading.Lock()

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "WebODMClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _response_detail(response: requests.Response) -> str:
        try:
            return json.dumps(response.json(), ensure_ascii=False)[:1000]
        except ValueError:
            return response.text[:1000]

    def _expect_ok(self, response: requests.Response, action: str) -> None:
        if response.ok:
            return
        if response.status_code in {401, 403}:
            code = "WEBODM_AUTH_FAILED"
            retryable = False
            detail = f"{action}失败：账号或密码无效（HTTP {response.status_code}）。"
        elif response.status_code in {502, 503, 504}:
            code = "WEBODM_UNAVAILABLE"
            retryable = True
            detail = (
                f"WebODM 远端服务暂不可用（HTTP {response.status_code}）。"
                "服务器网关没有连接到可用的 WebODM 上游服务；请在云服务器上启动或重启 "
                "WebODM 后重试，暂时无法恢复时可切换为本地 OpenCV 模式。"
            )
        else:
            code = "WEBODM_REQUEST_FAILED"
            retryable = response.status_code >= 500 or response.status_code == 429
            detail = (
                f"{action}失败：HTTP {response.status_code}，"
                f"{self._response_detail(response)}"
            )
        raise WebODMResponseError(
            code,
            detail,
            retryable=retryable,
        )

    def _login(self, *, force: bool = False) -> str:
        with self._token_lock:
            if self._token and not force:
                return self._token
            response = self.session.post(
                f"{self.base_url}/api/token-auth/",
                data={"username": self.username, "password": self.password},
                timeout=self.request_timeout,
                verify=self.verify_ssl,
            )
            self._expect_ok(response, "登录 WebODM")
            try:
                token = response.json().get("token")
            except ValueError as exc:
                raise WebODMResponseError(
                    "WEBODM_INVALID_RESPONSE",
                    "WebODM 登录响应不是有效 JSON。",
                    retryable=False,
                ) from exc
            if not token:
                raise WebODMResponseError(
                    "WEBODM_INVALID_RESPONSE",
                    "WebODM 登录成功，但响应中没有 token。",
                    retryable=False,
                )
            self._token = str(token)
            return self._token

    def _request(
        self,
        method: str,
        path: str,
        *,
        retry_token: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        supplied_headers = dict(kwargs.pop("headers", {}))
        headers = {"Authorization": f"JWT {self._login()}"}
        headers.update(supplied_headers)
        kwargs.setdefault("timeout", self.request_timeout)
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            verify=self.verify_ssl,
            **kwargs,
        )
        if response.status_code in {401, 403} and retry_token:
            response.close()
            self._login(force=True)
            return self._request(
                method,
                path,
                retry_token=False,
                headers=supplied_headers,
                **kwargs,
            )
        return response

    @staticmethod
    def _items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            items = payload.get("results", [])
            return [item for item in items if isinstance(item, dict)]
        return []

    def find_project(self, name: str) -> int | None:
        response = self._request("GET", "/api/projects/", params={"name": name, "page": 1})
        self._expect_ok(response, "查询 WebODM 项目")
        for item in self._items(response.json()):
            if item.get("name") == name:
                return int(item["id"])
        return None

    def create_project(self, name: str, description: str) -> int:
        response = self._request(
            "POST",
            "/api/projects/",
            data={"name": name, "description": description},
        )
        self._expect_ok(response, "创建 WebODM 项目")
        return int(response.json()["id"])

    def find_task(self, project_id: int, name: str) -> dict[str, Any] | None:
        response = self._request(
            "GET",
            f"/api/projects/{project_id}/tasks/",
            params={"name": name, "page": 1},
        )
        self._expect_ok(response, "查询 WebODM 任务")
        matches = [item for item in self._items(response.json()) if item.get("name") == name]
        if not matches:
            return None
        return max(matches, key=lambda item: int(item.get("id", 0)))

    def create_task(
        self,
        project_id: int,
        sources: list[MosaicSource],
        *,
        name: str,
        orthophoto_resolution: float,
    ) -> int:
        options = [
            {"name": "orthophoto-resolution", "value": orthophoto_resolution},
            {"name": "orthophoto-png", "value": True},
            {"name": "skip-3dmodel", "value": True},
            {"name": "auto-boundary", "value": True},
        ]
        with ExitStack() as stack:
            files: list[tuple[str, tuple[str, Any, str]]] = []
            for source in sources:
                handle = stack.enter_context(source.path.open("rb"))
                mime_type = mimetypes.guess_type(source.path.name)[0] or "image/jpeg"
                files.append(("images", (source.display_name or source.path.name, handle, mime_type)))
            response = self._request(
                "POST",
                f"/api/projects/{project_id}/tasks/",
                data={"name": name, "options": json.dumps(options)},
                files=files,
                retry_token=False,
            )
        self._expect_ok(response, "上传影像并创建 WebODM 任务")
        return int(response.json()["id"])

    def get_task(self, project_id: int, task_id: int) -> dict[str, Any]:
        response = self._request(
            "GET", f"/api/projects/{project_id}/tasks/{task_id}/"
        )
        self._expect_ok(response, "查询 WebODM 任务状态")
        return response.json()

    def cancel_task(self, project_id: int, task_id: int) -> None:
        response = self._request(
            "POST",
            f"/api/projects/{project_id}/tasks/{task_id}/cancel/",
        )
        self._expect_ok(response, "取消 WebODM 任务")

    def download_asset(
        self, project_id: int, task_id: int, asset: str, output_path: Path
    ) -> Path:
        response = self._request(
            "GET",
            f"/api/projects/{project_id}/tasks/{task_id}/download/{asset}",
            stream=True,
        )
        self._expect_ok(response, f"下载 WebODM 产物 {asset}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_suffix(output_path.suffix + ".part")
        try:
            with temporary_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            temporary_path.replace(output_path)
        finally:
            response.close()
            temporary_path.unlink(missing_ok=True)
        return output_path


def _save_jpeg(image: Image.Image, path: Path, *, max_side: int, quality: int) -> tuple[int, int]:
    rgb = image.convert("RGBA")
    background = Image.new("RGB", rgb.size, "white")
    background.paste(rgb, mask=rgb.getchannel("A"))
    rgb.close()
    background.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    background.save(path, format="JPEG", quality=quality, optimize=True)
    size = background.size
    background.close()
    return size


def render_web_images(
    png_path: Path,
    mosaic_path: Path,
    preview_path: Path,
    *,
    max_side: int,
    quality: int,
) -> tuple[int, int]:
    # WebODM output is trusted but can legitimately exceed Pillow's generic
    # decompression-bomb threshold. Limit the persisted JPEG dimensions instead.
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(png_path) as source:
            width, height = _save_jpeg(
                source, mosaic_path, max_side=max_side, quality=quality
            )
        with Image.open(mosaic_path) as source:
            _save_jpeg(source, preview_path, max_side=1600, quality=min(quality, 88))
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit
    return width, height


class WebODMMosaicEngine:
    name = "webodm"
    strategy = "webodm_orthophoto"

    def __init__(
        self,
        *,
        base_url: str | None,
        username: str | None,
        password: str | None,
        verify_ssl: bool,
        poll_seconds: int,
        request_timeout_seconds: int,
        orthophoto_resolution: float,
        jpeg_max_side: int,
        jpeg_quality: int,
    ) -> None:
        self.base_url = str(base_url or "").strip()
        self.username = str(username or "").strip()
        self.password = str(password or "")
        self.verify_ssl = verify_ssl
        self.poll_seconds = poll_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.orthophoto_resolution = orthophoto_resolution
        self.jpeg_max_side = jpeg_max_side
        self.jpeg_quality = jpeg_quality

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not self.username
            or not self.password
        ):
            raise MosaicEngineError(
                "MOSAIC_ENGINE_NOT_CONFIGURED",
                "WebODM 拼接已启用，但地址、用户名或密码尚未完整配置。",
            )

    def run(
        self,
        sources: list[MosaicSource],
        work_directory: Path,
        options: dict[str, Any],
        progress,
        is_canceled,
    ) -> MosaicResult:
        if len(sources) < 2:
            raise MosaicEngineError(
                "MOSAIC_INPUT_INSUFFICIENT", "WebODM 拼接至少需要两张影像。"
            )
        work_directory.mkdir(parents=True, exist_ok=True)
        local_task_id = work_directory.parents[1].name
        local_job_id = work_directory.name
        project_name = f"MosquitoMapper-{local_task_id}"
        task_name = f"拼接-{local_job_id}"
        orthophoto_resolution = float(
            options.get("orthophoto_resolution") or self.orthophoto_resolution
        )
        project_id: int | None = None
        task_id: int | None = None

        try:
            progress(5, "webodm_connect", "正在连接外部 WebODM 服务")
            raise_if_canceled(is_canceled)
            with WebODMClient(
                self.base_url,
                self.username,
                self.password,
                verify_ssl=self.verify_ssl,
                request_timeout_seconds=self.request_timeout_seconds,
            ) as client:
                project_id = client.find_project(project_name)
                if project_id is None:
                    project_id = client.create_project(
                        project_name,
                        f"MosquitoMapper 任务 {local_task_id} 自动创建",
                    )
                progress(12, "webodm_project", "WebODM 项目已就绪")
                raise_if_canceled(is_canceled)

                existing = client.find_task(project_id, task_name)
                if existing is None:
                    progress(18, "webodm_upload", f"正在向 WebODM 上传 {len(sources)} 张影像")
                    task_id = client.create_task(
                        project_id,
                        sources,
                        name=task_name,
                        orthophoto_resolution=orthophoto_resolution,
                    )
                else:
                    task_id = int(existing["id"])

                progress(28, "webodm_queued", "影像已提交，等待 WebODM 处理")
                while True:
                    if is_canceled():
                        try:
                            client.cancel_task(project_id, task_id)
                        finally:
                            raise MosaicCanceled
                    task = client.get_task(project_id, task_id)
                    status = int(task.get("status") or 0)
                    if status == 40:
                        break
                    if status == 30:
                        detail = str(task.get("last_error") or "WebODM 未返回错误详情")
                        raise MosaicEngineError(
                            "WEBODM_TASK_FAILED", f"WebODM 拼接失败：{detail}", retryable=False
                        )
                    if status == 50:
                        raise MosaicCanceled
                    running = float(task.get("running_progress") or 0.0)
                    if running > 1:
                        running /= 100.0
                    value = 30 if status == 10 else 35 + round(max(0.0, min(1.0, running)) * 45)
                    progress(
                        value,
                        "webodm_processing",
                        f"WebODM {TASK_STATUS.get(status, '处理中')}，远程进度 {running * 100:.0f}%",
                    )
                    time.sleep(self.poll_seconds)

                assets = {str(item) for item in task.get("available_assets") or []}
                required = {"orthophoto.tif", "orthophoto.png"}
                missing = sorted(required - assets)
                if missing:
                    raise MosaicEngineError(
                        "WEBODM_ASSET_MISSING",
                        "WebODM 已完成任务，但缺少产物：" + "、".join(missing),
                    )

                progress(82, "webodm_download", "正在下载 WebODM GeoTIFF 正射影像")
                geotiff_path = client.download_asset(
                    project_id, task_id, "orthophoto.tif", work_directory / "orthophoto.tif"
                )
                raise_if_canceled(is_canceled)
                progress(89, "webodm_download", "正在下载 WebODM 网页影像")
                png_path = client.download_asset(
                    project_id, task_id, "orthophoto.png", work_directory / "orthophoto.png"
                )

            progress(94, "web_render", "正在生成平台拼接图与网页预览")
            mosaic_path = work_directory / "mosaic.jpg"
            preview_path = work_directory / "preview.jpg"
            width, height = render_web_images(
                png_path,
                mosaic_path,
                preview_path,
                max_side=self.jpeg_max_side,
                quality=self.jpeg_quality,
            )
            png_path.unlink(missing_ok=True)
            progress(98, "quality_check", "正在登记 WebODM 拼接产物")
            return MosaicResult(
                mosaic_path=mosaic_path,
                preview_path=preview_path,
                width=width,
                height=height,
                mosaic_filename="mosaic.jpg",
                mosaic_mime_type="image/jpeg",
                extra_artifacts=[
                    MosaicExtraArtifact(
                        kind="mosaic_geotiff",
                        path=geotiff_path,
                        filename="orthophoto.tif",
                        mime_type="image/tiff",
                    )
                ],
                quality_summary={
                    "provider": self.name,
                    "strategy": self.strategy,
                    "source_count": len(sources),
                    "source_image_count": len(sources),
                    "gps_count": sum(source.has_gps for source in sources),
                    "orthophoto_resolution_cm_per_pixel": orthophoto_resolution,
                    "webodm_project_id": project_id,
                    "webodm_task_id": task_id,
                    "webodm_base_url": self.base_url,
                    "geotiff_preserved": True,
                    "web_image_max_side": self.jpeg_max_side,
                    "notes": "主拼接图由 WebODM 正射影像生成；原始 GeoTIFF 作为独立产物保留。",
                },
            )
        except MosaicCanceled:
            raise
        except MosaicEngineError:
            if project_id is not None and task_id is not None:
                try:
                    with WebODMClient(
                        self.base_url,
                        self.username,
                        self.password,
                        verify_ssl=self.verify_ssl,
                        request_timeout_seconds=self.request_timeout_seconds,
                    ) as cleanup_client:
                        cleanup_client.cancel_task(project_id, task_id)
                except Exception:
                    pass
            raise
        except WebODMResponseError as exc:
            raise MosaicEngineError(
                exc.code, exc.detail, retryable=exc.retryable
            ) from exc
        except requests.RequestException as exc:
            raise MosaicEngineError(
                "WEBODM_UNREACHABLE",
                f"无法连接 WebODM 服务：{type(exc).__name__}。",
                retryable=True,
            ) from exc
        except (OSError, ValueError) as exc:
            raise MosaicEngineError(
                "WEBODM_RESULT_INVALID",
                f"处理 WebODM 拼接产物失败：{type(exc).__name__}。",
                retryable=False,
            ) from exc
