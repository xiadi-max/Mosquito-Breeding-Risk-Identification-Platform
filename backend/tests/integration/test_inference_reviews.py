from __future__ import annotations

from PIL import Image

from app.core.security import resolve_storage_path
from app.worker import run_worker
from tests.integration.test_rois_grids import seed_task_and_mosaic


def build_grid(client, settings):
    task_id, mosaic_id = seed_task_and_mosaic(settings, width=1000, height=900)
    mosaic_path = resolve_storage_path(
        settings.resolved_storage_root,
        f"tasks/{task_id}/mosaic/test/mosaic.png",
    )
    mosaic_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1000, 900), "#78956f").save(mosaic_path, format="PNG")
    saved = client.put(
        f"/api/v1/tasks/{task_id}/rois",
        json={
            "expected_version": 0,
            "source_artifact_id": mosaic_id,
            "items": [
                {
                    "code": "ROI-01",
                    "polygon": [[0, 0], [1000, 0], [1000, 900], [0, 900]],
                }
            ],
        },
    )
    assert saved.status_code == 200
    preview = client.post(
        f"/api/v1/tasks/{task_id}/grid-plans/preview",
        json={"roi_version": 1},
    ).json()
    queued = client.put(
        f"/api/v1/tasks/{task_id}/grid-plan",
        json={"roi_version": 1, "fingerprint": preview["fingerprint"]},
    )
    assert queued.status_code == 202
    assert run_worker(once=True, settings=settings) == 0
    plan = client.get(f"/api/v1/tasks/{task_id}/grid-plan").json()
    return task_id, plan["id"]


def test_fake_inference_idempotency_detection_query_and_review(test_settings, migrated_client):
    task_id, grid_id = build_grid(migrated_client, test_settings)
    body = {
        "grid_plan_id": grid_id,
        "provider": "fake",
        "infer_min_confidence": 0.2,
        "review_threshold": 0.5,
        "auto_accept_threshold": 0.8,
        "nms_iou": 0.45,
    }
    queued = migrated_client.post(
        f"/api/v1/tasks/{task_id}/inference-jobs",
        headers={"Idempotency-Key": "m4-inference"},
        json=body,
    )
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["job"]["id"]
    replay = migrated_client.post(
        f"/api/v1/tasks/{task_id}/inference-jobs",
        headers={"Idempotency-Key": "m4-inference"},
        json=body,
    )
    assert replay.status_code == 202
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["job"]["id"] == job_id

    assert run_worker(once=True, settings=test_settings) == 0
    job = migrated_client.get(f"/api/v1/jobs/{job_id}").json()["job"]
    assert job["status"] == "succeeded", job
    assert job["result"]["demo"] is True
    assert job["result"]["stats"]["accepted"] > 0
    assert job["result"]["stats"]["pending"] > 0

    detections = migrated_client.get(f"/api/v1/tasks/{task_id}/detections")
    assert detections.status_code == 200, detections.text
    data = detections.json()
    assert data["thresholds"] == {
        "auto_accept_threshold": 0.8,
        "infer_min_confidence": 0.2,
        "review_threshold": 0.5,
    }
    assert all(item["confidence"] >= 0.2 for item in data["items"])
    assert all(item["crop_artifact_id"] for item in data["items"])

    reviews = migrated_client.get(
        f"/api/v1/tasks/{task_id}/reviews", params={"status": "pending"}
    ).json()
    candidate = reviews["items"][0]
    crop = migrated_client.get(
        f"/api/v1/artifacts/{candidate['crop_artifact_id']}/content"
    )
    assert crop.status_code == 200
    assert crop.content.startswith(b"\xff\xd8")

    accepted = migrated_client.patch(
        f"/api/v1/tasks/{task_id}/reviews/{candidate['id']}",
        json={"action": "accept", "comment": "人工确认", "expected_version": 1},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["detection"]["effective_state"] == "accepted"
    assert accepted.json()["review_snapshot_version"] == 1
    assert accepted.json()["invalidated"] == ["risk_run", "decision", "exports"]

    conflict = migrated_client.patch(
        f"/api/v1/tasks/{task_id}/reviews/{candidate['id']}",
        json={"action": "reject", "expected_version": 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "VERSION_CONFLICT"

    reset = migrated_client.patch(
        f"/api/v1/tasks/{task_id}/reviews/{candidate['id']}",
        json={"action": "reset", "expected_version": 2},
    )
    assert reset.status_code == 200
    assert reset.json()["detection"]["effective_state"] == "pending"
    assert reset.json()["detection"]["version"] == 3

    task = migrated_client.get(f"/api/v1/tasks/{task_id}").json()
    assert task["progress"] == 71
    assert task["current_stage"] == "inference"
    assert task["blocked_by"]["code"] == "PENDING_REVIEWS"
    dashboard = migrated_client.get(
        "/api/mosquito-workbench/dashboard", params={"task_id": task_id}
    ).json()
    assert dashboard["model"]["completedTargetCount"] > 0
    assert dashboard["model"]["reviews"]


def test_roi_change_marks_inference_stale(test_settings, migrated_client):
    task_id, grid_id = build_grid(migrated_client, test_settings)
    queued = migrated_client.post(
        f"/api/v1/tasks/{task_id}/inference-jobs",
        json={"grid_plan_id": grid_id, "provider": "fake"},
    )
    assert queued.status_code == 202
    assert run_worker(once=True, settings=test_settings) == 0
    assert migrated_client.get(f"/api/v1/tasks/{task_id}/detections").json()["run_status"] == "current"

    roi = migrated_client.get(f"/api/v1/tasks/{task_id}/rois").json()
    changed = migrated_client.put(
        f"/api/v1/tasks/{task_id}/rois",
        json={
            "expected_version": roi["version"],
            "source_artifact_id": roi["source"]["artifact_id"],
            "items": [
                {
                    "code": "ROI-01",
                    "polygon": [[20, 20], [800, 20], [800, 700], [20, 700]],
                }
            ],
        },
    )
    assert changed.status_code == 200
    assert migrated_client.get(f"/api/v1/tasks/{task_id}/detections").json()["run_id"] is None


def test_inference_openapi_paths_are_registered(migrated_client):
    paths = migrated_client.get("/openapi.json").json()["paths"]
    assert "/api/v1/tasks/{task_id}/inference-jobs" in paths
    assert "/api/v1/tasks/{task_id}/detections" in paths
    assert "/api/v1/tasks/{task_id}/reviews" in paths
    assert "/api/v1/tasks/{task_id}/reviews/{detection_id}" in paths
