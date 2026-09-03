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


def check(response: httpx.Response, expected: int) -> dict:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}: {response.text}"
        )
    return response.json() if response.content else {}


def image_bytes(color: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (48, 32), color).save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="M2 API + worker smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    task_id: str | None = None
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        version = check(client.get("/api/v1/version"), 200)
        if version["schema_revision"] != "20260811_0003":
            raise RuntimeError(f"database is not at M2 head: {version}")

        stamp = datetime.now(UTC).strftime("%H%M%S")
        task = check(
            client.post(
                "/api/v1/tasks",
                json={
                    "name": f"M2 smoke test {stamp}",
                    "area": "M2 validation area",
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
                    files=[
                        ("files", ("a.png", image_bytes("red"), "image/png")),
                        ("files", ("b.png", image_bytes("green"), "image/png")),
                    ],
                ),
                201,
            )
            if len(uploaded["accepted"]) != 2:
                raise RuntimeError(f"images were not accepted: {uploaded}")

            job_resource = check(
                client.post(
                    f"/api/v1/tasks/{task_id}/mosaic-jobs",
                    headers={"Idempotency-Key": f"m2-smoke-{stamp}"},
                    json={"provider": "fake", "options": {}},
                ),
                202,
            )
            job_id = job_resource["job"]["id"]

            worker = subprocess.run(
                [sys.executable, "-m", "app.worker", "--once"],
                cwd=BACKEND_ROOT,
                check=False,
            )
            if worker.returncode != 0:
                raise RuntimeError(f"worker exited with code {worker.returncode}")

            completed = check(client.get(f"/api/v1/jobs/{job_id}"), 200)["job"]
            if completed["status"] != "succeeded":
                raise RuntimeError(f"mosaic job did not succeed: {completed}")
            if completed["result"]["quality"]["demo"] is not True:
                raise RuntimeError("fake mosaic was not marked as demo")

            mosaic_id = completed["result"]["mosaic_artifact_id"]
            artifact = client.get(f"/api/v1/artifacts/{mosaic_id}/content")
            if artifact.status_code != 200 or not artifact.content.startswith(b"\x89PNG"):
                raise RuntimeError("mosaic artifact is not a valid PNG response")

            task_after = check(client.get(f"/api/v1/tasks/{task_id}"), 200)
            if task_after["progress"] != 28:
                raise RuntimeError(f"task progress is not 28: {task_after}")

            events = client.get(f"/api/v1/jobs/{job_id}/events")
            if events.status_code != 200 or "event: job.succeeded" not in events.text:
                raise RuntimeError("SSE terminal event was not replayed")
        finally:
            if task_id:
                cleanup = client.delete(f"/api/v1/tasks/{task_id}")
                if cleanup.status_code not in {204, 404}:
                    raise RuntimeError(f"cleanup failed: {cleanup.text}")

    print("M2 smoke test passed: queue, worker, progress, SSE, mosaic artifacts, cleanup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
