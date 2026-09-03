from __future__ import annotations

import argparse
from datetime import UTC, datetime
from io import BytesIO

import httpx
from PIL import Image


def check(response: httpx.Response, expected: int) -> dict:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}: {response.text}"
        )
    if response.content:
        return response.json()
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 API smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    task_id: str | None = None
    with httpx.Client(base_url=args.base_url, timeout=20) as client:
        live = check(client.get("/api/v1/health/live"), 200)
        if live["status"] != "ok":
            raise RuntimeError("live check failed")

        stamp = datetime.now(UTC).strftime("%H%M%S")
        created = check(
            client.post(
                "/api/v1/tasks",
                json={
                    "name": f"M1 smoke test {stamp}",
                    "area": "M1 validation area",
                    "survey_date": datetime.now(UTC).date().isoformat(),
                    "task_type": "例行巡查",
                },
            ),
            201,
        )
        task_id = created["id"]

        try:
            image_buffer = BytesIO()
            Image.new("RGB", (32, 24), "green").save(image_buffer, format="PNG")
            uploaded = check(
                client.post(
                    f"/api/v1/tasks/{task_id}/images",
                    files={
                        "files": (
                            "m1-smoke.jpg",
                            image_buffer.getvalue(),
                            "application/octet-stream",
                        )
                    },
                ),
                201,
            )
            if len(uploaded["accepted"]) != 1:
                raise RuntimeError(f"upload was not accepted: {uploaded}")

            artifact_id = uploaded["accepted"][0]["artifact_id"]
            artifact = client.get(f"/api/v1/artifacts/{artifact_id}/content")
            if artifact.status_code != 200 or artifact.content != image_buffer.getvalue():
                raise RuntimeError("artifact download did not match upload")

            dashboard = check(
                client.get(
                    "/api/mosquito-workbench/dashboard",
                    params={"task_id": task_id},
                ),
                200,
            )
            if dashboard["meta"]["current_task_id"] != task_id:
                raise RuntimeError("dashboard did not select the created task")
            if dashboard["tasks"][0]["progress"] != 14:
                raise RuntimeError("task progress did not advance to 14")

            task = check(client.get(f"/api/v1/tasks/{task_id}"), 200)
            patched = check(
                client.patch(
                    f"/api/v1/tasks/{task_id}",
                    headers={"If-Match": f'"{task["version"]}"'},
                    json={"area": "M1 validation area updated"},
                ),
                200,
            )
            check(
                client.post(
                    f"/api/v1/tasks/{task_id}/archive",
                    headers={"If-Match": f'"{patched["version"]}"'},
                ),
                200,
            )
        finally:
            if task_id is not None:
                response = client.delete(f"/api/v1/tasks/{task_id}")
                if response.status_code not in {204, 404}:
                    raise RuntimeError(f"cleanup failed: {response.text}")

    print("M1 smoke test passed: task, upload, artifact, dashboard, versioning, cleanup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

