from pathlib import Path
import shutil
from PIL import Image, ImageOps
from app.adapters.mosaic.base import MosaicEngineError, MosaicResult, raise_if_canceled


class ImportedMosaicEngine:
    name = "imported"

    def validate(self):
        pass

    def run(self, sources, work_directory, options, progress, is_canceled):
        if len(sources) != 1:
            raise MosaicEngineError("MOSAIC_IMPORT_REQUIRES_ONE_IMAGE", "请选择一张已拼接图像。")
        raise_if_canceled(is_canceled)
        progress(20, "import", "正在导入已拼接图像，不执行拼接")
        with Image.open(sources[0].path) as original:
            image = ImageOps.exif_transpose(original)
            width, height = image.size
            if original.getexif().get(274, 1) == 1:
                suffix = ".jpg" if original.format == "JPEG" else ".png"
                mosaic = work_directory / ("mosaic" + suffix)
                shutil.copyfile(sources[0].path, mosaic)
            else:
                mosaic = work_directory / "mosaic.png"
                image.save(mosaic)
            preview = image.convert("RGB")
            preview.thumbnail((1600, 1600))
            preview_path = work_directory / "preview.jpg"
            preview.save(preview_path, quality=90)
        raise_if_canceled(is_canceled)
        progress(90, "import", "已拼接图像已导入")
        return MosaicResult(
            mosaic_path=mosaic, preview_path=preview_path, width=width, height=height,
            mosaic_filename=mosaic.name,
            mosaic_mime_type="image/jpeg" if mosaic.suffix == ".jpg" else "image/png",
            quality_summary={"source_count": 1, "imported": True, "method": "prestitched"},
        )
