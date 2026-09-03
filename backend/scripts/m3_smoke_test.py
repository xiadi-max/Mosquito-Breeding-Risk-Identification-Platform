from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image


BACKEND_ROOT = Path(__file__).resolve().parents[1]
M3_SCHEMA_REVISION = "20260813_0004"


def check(response: httpx.Response, expected: int) -> dict:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}: {response.text}"
        )
    return response.json() if response.content else {}


def image_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1000, 900), "#6e8f72").save(buffer, format="PNG")
    return buffer.getvalue()


def run_one_worker() -> None:
    worker = subprocess.run(
        [sys.executable, "-m", "app.worker", "--once"],
        cwd=BACKEND_ROOT,
        check=False,
    )
    if worker.returncode != 0:
        raise RuntimeError(f"worker exited with code {worker.returncode}")


def completed_job(client: httpx.Client, job_id: str, job_name: str) -> dict:
    job = check(client.get(f"/api/v1/jobs/{job_id}"), 200)["job"]
    if job["status"] != "succeeded":
        raise RuntimeError(f"{job_name} job did not succeed: {job}")
    return job


def main() -> int:
    parser = argparse.ArgumentParser(description="M3 ROI + grid API/worker smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    task_id: str | None = None
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        version = check(client.get("/api/v1/version"), 200)
        if version["schema_revision"] != M3_SCHEMA_REVISION:
            raise RuntimeError(f"database is not at M3 head: {version}")

        stamp = datetime.now(UTC).strftime("%H%M%S")
        task = check(
            client.post(
                "/api/v1/tasks",
                json={
                    "name": f"M3 smoke test {stamp}",
                    "area": "M3 validation area",
                    "survey_date": datetime.now(UTC).date().isoformat(),
                    "task_type": "例行巡查",
                },
            ),
            201,
        )
        task_id = task["id"]
        try:
            uploaded = check(
                client.post(
                    f"/api/v1/tasks/{task_id}/images",
                    files=[("files", ("m3-source.png", image_bytes(), "image/png"))],
                ),
                201,
            )
            if len(uploaded["accepted"]) != 1:
                raise RuntimeError(f"source image was not accepted: {uploaded}")

            mosaic = check(
                client.post(
                    f"/api/v1/tasks/{task_id}/mosaic-jobs",
                    headers={"Idempotency-Key": f"m3-mosaic-{stamp}"},
        json={"provider": "fake", "options": {}},
                ),
                202,
            )
            run_one_worker()
            mosaic_job = completed_job(client, mosaic["job"]["id"], "mosaic")
            result = mosaic_job["result"]
            mosaic_id = result["mosaic_artifact_id"]
            width, height = result["width"], result["height"]

            rois = check(
                client.put(
                    f"/api/v1/tasks/{task_id}/rois",
                    json={
                        "expected_version": 0,
                        "source_artifact_id": mosaic_id,
                        "coordinate_space": "mosaic_pixel",
                        "items": [
                            {
                                "code": "ROI-01",
                                "visible": True,
                                "polygon": [
                                    [0, 0],
                                    [width, 0],
                                    [width, height],
                                    [0, height],
                                ],
                            }
                        ],
                    },
                ),
                200,
            )
            if rois["version"] != 1 or len(rois["items"]) != 1:
                raise RuntimeError(f"ROI version was not persisted: {rois}")

            preview = check(
                client.post(
                    f"/api/v1/tasks/{task_id}/grid-plans/preview",
                    json={
                        "roi_version": 1,
                        "tile_size": 640,
                        "overlap": 0.2,
                        "edge_strategy": "pad",
                        "min_roi_intersection": 0.1,
                    },
                ),
                200,
            )
            if preview["count"] < 1:
                raise RuntimeError(f"grid preview is empty: {preview}")

            grid = check(
                client.put(
                    f"/api/v1/tasks/{task_id}/grid-plan",
                    headers={"Idempotency-Key": f"m3-grid-{stamp}"},
                    json={
                        "roi_version": 1,
                        "tile_size": 640,
                        "overlap": 0.2,
                        "edge_strategy": "pad",
                        "min_roi_intersection": 0.1,
                        "fingerprint": preview["fingerprint"],
                    },
                ),
                202,
            )
            run_one_worker()
            completed_job(client, grid["job"]["id"], "grid")

            plan = check(client.get(f"/api/v1/tasks/{task_id}/grid-plan"), 200)
            if plan["count"] != preview["count"] or len(plan["tiles"]) != plan["count"]:
                raise RuntimeError(f"persisted grid does not match preview: {plan}")

            task_after = check(client.get(f"/api/v1/tasks/{task_id}"), 200)
            if task_after["progress"] != 57 or task_after["current_stage"] != "grid":
                raise RuntimeError(f"task did not reach M3 grid stage: {task_after}")

            dashboard = check(
                client.get("/api/mosquito-workbench/dashboard", params={"task_id": task_id}),
                200,
            )
            if len(dashboard["rois"]) != 1:
                raise RuntimeError("dashboard compatibility response has no saved ROI")
        finally:
            if task_id:
                cleanup = client.delete(f"/api/v1/tasks/{task_id}")
                if cleanup.status_code not in {204, 404}:
                    raise RuntimeError(f"cleanup failed: {cleanup.text}")

    print(
        "M3 smoke test passed: mosaic, ROI version, grid preview, "
        "grid worker, 57% progress, dashboard, cleanup"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
