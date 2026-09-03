from __future__ import annotations

import argparse
from datetime import UTC, datetime

import httpx

from m3_smoke_test import check, completed_job, image_bytes, run_one_worker


M4_SCHEMA_REVISION = "20260813_0005"


def main() -> int:
    parser = argparse.ArgumentParser(description="M4 inference + review smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    task_id: str | None = None
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        version = check(client.get("/api/v1/version"), 200)
        if version["schema_revision"] != M4_SCHEMA_REVISION:
            raise RuntimeError(f"database is not at M4 head: {version}")

        stamp = datetime.now(UTC).strftime("%H%M%S%f")
        task = check(
            client.post(
                "/api/v1/tasks",
                json={
                    "name": f"M4 smoke test {stamp}",
                    "area": "M4 validation area",
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
                    files=[("files", ("m4-source.png", image_bytes(), "image/png"))],
                ),
                201,
            )
            if len(uploaded["accepted"]) != 1:
                raise RuntimeError(f"source image was not accepted: {uploaded}")

            mosaic = check(
                client.post(
                    f"/api/v1/tasks/{task_id}/mosaic-jobs",
                    headers={"Idempotency-Key": f"m4-mosaic-{stamp}"},
        json={"provider": "fake", "options": {}},
                ),
                202,
            )
            run_one_worker()
            mosaic_job = completed_job(client, mosaic["job"]["id"], "mosaic")
            mosaic_result = mosaic_job["result"]

            rois = check(
                client.put(
                    f"/api/v1/tasks/{task_id}/rois",
                    json={
                        "expected_version": 0,
                        "source_artifact_id": mosaic_result["mosaic_artifact_id"],
                        "items": [
                            {
                                "code": "ROI-01",
                                "polygon": [
                                    [0, 0],
                                    [mosaic_result["width"], 0],
                                    [mosaic_result["width"], mosaic_result["height"]],
                                    [0, mosaic_result["height"]],
                                ],
                            }
                        ],
                    },
                ),
                200,
            )
            preview = check(
                client.post(
                    f"/api/v1/tasks/{task_id}/grid-plans/preview",
                    json={"roi_version": rois["version"]},
                ),
                200,
            )
            grid = check(
                client.put(
                    f"/api/v1/tasks/{task_id}/grid-plan",
                    headers={"Idempotency-Key": f"m4-grid-{stamp}"},
                    json={
                        "roi_version": rois["version"],
                        "fingerprint": preview["fingerprint"],
                    },
                ),
                202,
            )
            run_one_worker()
            completed_job(client, grid["job"]["id"], "grid")
            plan = check(client.get(f"/api/v1/tasks/{task_id}/grid-plan"), 200)

            inference_body = {
                "grid_plan_id": plan["id"],
                "provider": "fake",
                "infer_min_confidence": 0.2,
                "review_threshold": 0.5,
                "auto_accept_threshold": 0.8,
                "nms_iou": 0.45,
            }
            inference = check(
                client.post(
                    f"/api/v1/tasks/{task_id}/inference-jobs",
                    headers={"Idempotency-Key": f"m4-inference-{stamp}"},
                    json=inference_body,
                ),
                202,
            )
            replay = check(
                client.post(
                    f"/api/v1/tasks/{task_id}/inference-jobs",
                    headers={"Idempotency-Key": f"m4-inference-{stamp}"},
                    json=inference_body,
                ),
                202,
            )
            if replay["job"]["id"] != inference["job"]["id"]:
                raise RuntimeError("inference idempotency replay created another job")

            run_one_worker()
            inference_job = completed_job(
                client, inference["job"]["id"], "inference"
            )
            stats = inference_job["result"]["stats"]
            if stats["accepted"] < 1 or stats["pending"] < 1:
                raise RuntimeError(f"fake inference states are incomplete: {stats}")

            reviews = check(
                client.get(
                    f"/api/v1/tasks/{task_id}/reviews",
                    params={"status": "pending"},
                ),
                200,
            )
            candidate = reviews["items"][0]
            crop = client.get(
                f"/api/v1/artifacts/{candidate['crop_artifact_id']}/content"
            )
            if crop.status_code != 200 or not crop.content.startswith(b"\xff\xd8"):
                raise RuntimeError("review crop is not a valid JPEG artifact")

            accepted = check(
                client.patch(
                    f"/api/v1/tasks/{task_id}/reviews/{candidate['id']}",
                    json={
                        "action": "accept",
                        "comment": "M4 smoke test",
                        "expected_version": candidate["version"],
                    },
                ),
                200,
            )
            if accepted["detection"]["effective_state"] != "accepted":
                raise RuntimeError(f"review accept was not applied: {accepted}")

            conflict = client.patch(
                f"/api/v1/tasks/{task_id}/reviews/{candidate['id']}",
                json={"action": "reject", "expected_version": candidate["version"]},
            )
            if conflict.status_code != 409 or conflict.json().get("code") != "VERSION_CONFLICT":
                raise RuntimeError("stale review version was not rejected")

            reset = check(
                client.patch(
                    f"/api/v1/tasks/{task_id}/reviews/{candidate['id']}",
                    json={
                        "action": "reset",
                        "expected_version": accepted["detection"]["version"],
                    },
                ),
                200,
            )
            if reset["detection"]["effective_state"] != "pending":
                raise RuntimeError(f"review reset did not restore auto state: {reset}")

            task_after = check(client.get(f"/api/v1/tasks/{task_id}"), 200)
            if task_after["progress"] != 71 or task_after["current_stage"] != "inference":
                raise RuntimeError(f"task did not reach M4 stage: {task_after}")
            if task_after["blocked_by"].get("code") != "PENDING_REVIEWS":
                raise RuntimeError(f"pending reviews were not reported: {task_after}")

            dashboard = check(
                client.get(
                    "/api/mosquito-workbench/dashboard",
                    params={"task_id": task_id},
                ),
                200,
            )
            if not dashboard["model"]["reviews"]:
                raise RuntimeError("dashboard has no pending review items")
        finally:
            if task_id:
                cleanup = client.delete(f"/api/v1/tasks/{task_id}")
                if cleanup.status_code not in {204, 404}:
                    raise RuntimeError(f"cleanup failed: {cleanup.text}")

    print(
        "M4 smoke test passed: inference idempotency, Fake Detector, NMS, "
        "review crop, accept/conflict/reset, 71% progress, dashboard, cleanup"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
