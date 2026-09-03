from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.mosaic.base import MosaicSource
from app.adapters.mosaic.opencv import OpenCVMosaicEngine, SUPPORTED_EXTENSIONS
from app.core.config import Settings


EXCLUDED_NAMES = {"opencv_stitched.jpg", "mosaic.jpg", "preview.jpg"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the production OpenCV SCANS adapter against a local image folder."
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BACKEND_ROOT / "data" / "opencv-validation",
    )
    args = parser.parse_args()

    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {input_dir}")
    paths = sorted(
        (
            path
            for path in input_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_EXTENSIONS
            and path.name.casefold() not in EXCLUDED_NAMES
        ),
        key=lambda path: path.name.casefold(),
    )
    if len(paths) < 2:
        raise SystemExit("At least two JPG, JPEG or PNG source images are required.")

    settings = Settings(_env_file=None)
    engine = OpenCVMosaicEngine(
        work_scale=settings.mosaic_work_scale,
        pano_confidence_threshold=settings.mosaic_pano_confidence_threshold,
        black_border_threshold=settings.mosaic_black_border_threshold,
        output_jpeg_quality=settings.mosaic_output_jpeg_quality,
    )
    sources = [
        MosaicSource(
            image_id=f"local-{index:03d}",
            path=path,
            sha256=sha256(path),
            has_gps=False,
            display_name=path.name,
        )
        for index, path in enumerate(paths, start=1)
    ]

    def progress(value: int, step: str, message: str) -> None:
        print(f"[{value:>3}%] {step}: {message}")

    result = engine.run(
        sources,
        output_dir,
        options={},
        progress=progress,
        is_canceled=lambda: False,
    )
    print("OpenCV SCANS validation passed")
    print(f"Sources: {len(sources)}")
    print(f"Output: {result.mosaic_path}")
    print(f"Preview: {result.preview_path}")
    print(f"Dimensions: {result.width} x {result.height}")
    print(f"Strategy: {result.quality_summary['strategy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
