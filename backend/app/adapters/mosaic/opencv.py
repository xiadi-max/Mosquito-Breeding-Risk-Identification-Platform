from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from PIL import Image

from app.adapters.mosaic.base import (
    CancelCheck,
    MosaicEngineError,
    MosaicResult,
    MosaicSource,
    ProgressCallback,
    raise_if_canceled,
)


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def opencv_runtime_available() -> bool:
    """Return whether both runtime modules required by the provider are installed."""
    return (
        importlib.util.find_spec("cv2") is not None
        and importlib.util.find_spec("numpy") is not None
    )


def _read_image(path: Path, work_scale: float):
    """Decode a possibly non-ASCII Windows path and apply the configured work scale."""
    import cv2
    import numpy as np

    try:
        encoded = np.fromfile(str(path), dtype=np.uint8)
    except OSError as exc:
        raise MosaicEngineError(
            "MOSAIC_INPUT_INVALID", f"无法读取影像文件：{path.name}。"
        ) from exc
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise MosaicEngineError(
            "MOSAIC_INPUT_INVALID", f"影像无法由 OpenCV 解码：{path.name}。"
        )
    if work_scale != 1:
        image = cv2.resize(
            image,
            None,
            fx=work_scale,
            fy=work_scale,
            interpolation=cv2.INTER_AREA,
        )
    return image


def _create_scans_stitcher(pano_confidence_threshold: float):
    import cv2

    # SCANS selects the affine model used by the validated latest implementation.
    stitcher = cv2.Stitcher.create(cv2.Stitcher_SCANS)
    stitcher.setPanoConfidenceThresh(pano_confidence_threshold)
    return stitcher


def _crop_black_border(image, threshold: int):
    """Crop the pure-black canvas surrounding the registered image content."""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    points = cv2.findNonZero((gray > threshold).astype(np.uint8))
    if points is None:
        return image, False
    x, y, width, height = cv2.boundingRect(points)
    cropped = image[y : y + height, x : x + width]
    return cropped, cropped.shape[:2] != image.shape[:2]


def _write_jpeg(path: Path, image, quality: int) -> None:
    import cv2

    ok, encoded = cv2.imencode(
        ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality]
    )
    if not ok:
        raise MosaicEngineError(
            "MOSAIC_RENDER_FAILED", "OpenCV 无法编码拼接产物。", retryable=True
        )
    try:
        encoded.tofile(str(path))
    except OSError as exc:
        raise MosaicEngineError(
            "MOSAIC_RENDER_FAILED", "OpenCV 无法写入拼接产物。", retryable=True
        ) from exc


def _stitch_error_detail(status: int) -> str:
    import cv2

    messages = {
        cv2.Stitcher_ERR_NEED_MORE_IMGS: (
            "有效匹配不足；请确认至少两张影像来自同一连续区域、相邻影像有充分重叠，"
            "且未混入无关照片。"
        ),
        cv2.Stitcher_ERR_HOMOGRAPHY_EST_FAIL: "仿射几何变换估计失败。",
        cv2.Stitcher_ERR_CAMERA_PARAMS_ADJUST_FAIL: "拼接参数优化失败。",
    }
    return messages.get(status, "未知拼接错误。")


class OpenCVMosaicEngine:
    """Affine feature-based stitching for overlapping, approximately planar scans."""

    name = "opencv"
    strategy = "opencv_scans_affine"

    def __init__(
        self,
        *,
        work_scale: float = 0.6,
        pano_confidence_threshold: float = 0.3,
        black_border_threshold: int = 2,
        output_jpeg_quality: int = 95,
    ) -> None:
        self.work_scale = work_scale
        self.pano_confidence_threshold = pano_confidence_threshold
        self.black_border_threshold = black_border_threshold
        self.output_jpeg_quality = output_jpeg_quality

    def validate(self) -> None:
        if not opencv_runtime_available():
            raise MosaicEngineError(
                "MOSAIC_ENGINE_NOT_CONFIGURED",
                "OpenCV 拼接已启用，但当前环境缺少 opencv-python-headless 或 numpy。",
            )
        try:
            import cv2

            if not hasattr(cv2, "Stitcher_SCANS") or not hasattr(cv2.Stitcher, "create"):
                raise AttributeError("SCANS stitcher API is unavailable")
        except (ImportError, AttributeError) as exc:
            raise MosaicEngineError(
                "MOSAIC_ENGINE_NOT_CONFIGURED",
                "当前 OpenCV 版本不支持 SCANS 仿射拼接，请重新安装项目依赖。",
            ) from exc

    def run(
        self,
        sources: list[MosaicSource],
        work_directory: Path,
        options: dict[str, Any],
        progress: ProgressCallback,
        is_canceled: CancelCheck,
    ) -> MosaicResult:
        self.validate()
        import cv2

        if len(sources) < 2:
            raise MosaicEngineError(
                "MOSAIC_INPUT_INSUFFICIENT", "OpenCV 拼接至少需要两张影像。"
            )
        unsupported = [
            source.display_name or source.path.name
            for source in sources
            if source.path.suffix.lower() not in SUPPORTED_EXTENSIONS
        ]
        if unsupported:
            names = "、".join(unsupported[:3])
            suffix = "等" if len(unsupported) > 3 else ""
            raise MosaicEngineError(
                "MOSAIC_INPUT_UNSUPPORTED",
                f"OpenCV 拼接仅支持 JPG、JPEG、PNG；不支持：{names}{suffix}。",
            )

        work_directory.mkdir(parents=True, exist_ok=True)
        progress(5, "preflight", "正在检查 SCANS 仿射拼接输入")
        ordered_sources = sorted(
            sources,
            key=lambda item: (item.display_name or item.path.name).casefold(),
        )
        arrays = []
        try:
            for index, source in enumerate(ordered_sources):
                raise_if_canceled(is_canceled)
                arrays.append(_read_image(source.path, self.work_scale))
                progress(
                    10 + int(25 * (index + 1) / len(ordered_sources)),
                    "load_images",
                    f"已读取并缩放 {index + 1}/{len(ordered_sources)} 张影像",
                )

            raise_if_canceled(is_canceled)
            progress(40, "feature_registration", "正在进行特征匹配与仿射几何配准")
            stitcher = _create_scans_stitcher(self.pano_confidence_threshold)
            status, stitched = stitcher.stitch(arrays)
            if status != cv2.Stitcher_OK or stitched is None:
                raise MosaicEngineError(
                    "MOSAIC_STITCH_FAILED",
                    f"OpenCV SCANS 拼接失败，状态码 {status}：{_stitch_error_detail(status)}",
                )

            raise_if_canceled(is_canceled)
            progress(72, "seam_blending", "曝光补偿与接缝融合已完成，正在裁切黑边")
            result, border_cropped = _crop_black_border(
                stitched, self.black_border_threshold
            )
            if result.size == 0:
                raise MosaicEngineError(
                    "MOSAIC_RENDER_FAILED", "裁切黑边后没有有效图像内容。"
                )

            # Keep source pixels unchanged before stitching. Optional denoise, CLAHE and
            # sharpening are deliberately not applied by default because they can damage
            # the local features needed for registration and create inconsistent seams.
            progress(82, "render", "正在输出 JPEG 拼接图与预览图")
            mosaic_path = work_directory / "mosaic.jpg"
            _write_jpeg(mosaic_path, result, self.output_jpeg_quality)
            with Image.open(mosaic_path) as mosaic:
                preview = mosaic.convert("RGB")
                preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                preview_path = work_directory / "preview.jpg"
                preview.save(preview_path, format="JPEG", quality=88, optimize=True)
                width, height = mosaic.size

            raise_if_canceled(is_canceled)
            progress(92, "quality_check", "正在生成 SCANS 拼接质量摘要")
            gps_count = sum(1 for source in ordered_sources if source.has_gps)
            return MosaicResult(
                mosaic_path=mosaic_path,
                preview_path=preview_path,
                width=width,
                height=height,
                mosaic_filename="mosaic.jpg",
                mosaic_mime_type="image/jpeg",
                quality_summary={
                    "engine": self.name,
                    "strategy": self.strategy,
                    "demo": False,
                    "measurement_grade": False,
                    "georeferenced": False,
                    "source_image_count": len(ordered_sources),
                    "gps_count": gps_count,
                    "gps_completeness": gps_count / len(ordered_sources),
                    "work_scale": self.work_scale,
                    "pano_confidence_threshold": self.pano_confidence_threshold,
                    "black_border_threshold": self.black_border_threshold,
                    "black_border_cropped": border_cropped,
                    "output_format": "jpeg",
                    "output_jpeg_quality": self.output_jpeg_quality,
                    "source_preprocessing": "none",
                    "exposure_and_seam_blending": "opencv_builtin",
                    "anomalous_images": [],
                    "warning": (
                        "该成果是近似共面重叠影像的像素级拼接图，不包含 CRS/GSD，"
                        "不能作为测绘级正射成果。"
                    ),
                },
            )
        except MosaicEngineError:
            raise
        except cv2.error as exc:
            raise MosaicEngineError(
                "MOSAIC_STITCH_FAILED",
                "OpenCV 在特征匹配或图像融合时发生错误，请检查影像完整性、重叠度和内存。",
            ) from exc
        except (OSError, ValueError, MemoryError) as exc:
            raise MosaicEngineError(
                "MOSAIC_STITCH_FAILED",
                "拼接过程中发生图像读取、编码或内存错误。",
            ) from exc

