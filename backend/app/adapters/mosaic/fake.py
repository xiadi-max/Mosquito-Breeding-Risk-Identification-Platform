from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageOps

from app.adapters.mosaic.base import (
    CancelCheck,
    MosaicEngineError,
    MosaicResult,
    MosaicSource,
    ProgressCallback,
    raise_if_canceled,
)


class FakeMosaicEngine:
    """Deterministic montage for tests and clearly marked demo environments."""

    name = "fake"

    def validate(self) -> None:
        return None

    def run(
        self,
        sources: list[MosaicSource],
        work_directory: Path,
        options: dict,
        progress: ProgressCallback,
        is_canceled: CancelCheck,
    ) -> MosaicResult:
        if not sources:
            raise MosaicEngineError("MOSAIC_INPUT_EMPTY", "没有可用于拼接的影像。")
        work_directory.mkdir(parents=True, exist_ok=True)
        progress(5, "preflight", "正在检查输入影像")
        raise_if_canceled(is_canceled)

        images: list[Image.Image] = []
        try:
            for index, source in enumerate(sources):
                raise_if_canceled(is_canceled)
                with Image.open(source.path) as opened:
                    converted = ImageOps.exif_transpose(opened).convert("RGB")
                    converted.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    images.append(converted.copy())
                progress(
                    10 + int(35 * (index + 1) / len(sources)),
                    "process",
                    f"已读取 {index + 1}/{len(sources)} 张影像",
                )

            columns = max(1, math.ceil(math.sqrt(len(images))))
            rows = math.ceil(len(images) / columns)
            cell_width = max(image.width for image in images)
            cell_height = max(image.height for image in images)
            canvas = Image.new(
                "RGB", (columns * cell_width, rows * cell_height), (238, 242, 240)
            )
            for index, image in enumerate(images):
                x = (index % columns) * cell_width
                y = (index // columns) * cell_height
                canvas.paste(image, (x, y))

            progress(65, "render", "正在生成确定性测试拼接图")
            raise_if_canceled(is_canceled)

            mosaic_path = work_directory / "mosaic.png"
            preview_path = work_directory / "preview.jpg"
            canvas.save(mosaic_path, format="PNG", optimize=True)
            preview = canvas.copy()
            preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            preview.save(preview_path, format="JPEG", quality=88, optimize=True)
            progress(90, "quality_check", "正在生成拼接质量摘要")
            raise_if_canceled(is_canceled)

            gps_count = sum(1 for source in sources if source.has_gps)
            return MosaicResult(
                mosaic_path=mosaic_path,
                preview_path=preview_path,
                width=canvas.width,
                height=canvas.height,
                quality_summary={
                    "engine": self.name,
                    "demo": True,
                    "measurement_grade": False,
                    "source_image_count": len(sources),
                    "gps_count": gps_count,
                    "gps_completeness": gps_count / len(sources),
                    "anomalous_images": [],
                    "warning": "Fake 输出仅用于测试和前端联调。",
                },
            )
        except MosaicCanceled:
            raise
        except MosaicEngineError:
            raise
        except (OSError, ValueError) as exc:
            raise MosaicEngineError(
                "MOSAIC_INPUT_INVALID",
                "Fake 拼接引擎无法读取一张或多张输入影像。",
                retryable=False,
            ) from exc
        finally:
            for image in images:
                image.close()
