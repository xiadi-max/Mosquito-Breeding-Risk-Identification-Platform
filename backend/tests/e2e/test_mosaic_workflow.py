from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image as PILImage

from app.worker import run_worker


def _png(color: str) -> bytes:
    buffer = BytesIO()
    PILImage.new("RGB", (40, 30), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.e2e
def test_fake_mosaic_worker_end_to_end_and_upstream_invalidation(
    migrated_client, test_settings
) -> None:
    task = migrated_client.post(
        "/api/v1/tasks",
        json={
            "name": "Fake 拼接 E2E",
            "area": "测试区域",
            "survey_date": "2026-08-11",
            "task_type": "重点区域排查",
        },
    ).json()
    task_id = task["id"]
    uploaded = migrated_client.post(
        f"/api/v1/tasks/{task_id}/images",
        files=[
            ("files", ("a.png", _png("red"), "image/png")),
            ("files", ("b.png", _png("green"), "image/png")),
        ],
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["summary"]["image_count"] == 2

    created = migrated_client.post(
        f"/api/v1/tasks/{task_id}/mosaic-jobs",
        headers={"Idempotency-Key": "e2e-mosaic-1"},
        json={"provider": "fake", "options": {}},
    )
    assert created.status_code == 202
    job_id = created.json()["job"]["id"]

    assert run_worker(once=True, settings=test_settings) == 0

    completed = migrated_client.get(f"/api/v1/jobs/{job_id}")
    assert completed.status_code == 200
    job = completed.json()["job"]
    assert job["status"] == "succeeded"
    assert job["progress"] == 100
    assert job["result"]["provider"] == "fake"
    assert job["result"]["quality"]["demo"] is True

    mosaic_id = job["result"]["mosaic_artifact_id"]
    preview_id = job["result"]["preview_artifact_id"]
    mosaic = migrated_client.get(f"/api/v1/artifacts/{mosaic_id}/content")
    preview = migrated_client.get(f"/api/v1/artifacts/{preview_id}/content")
    assert mosaic.status_code == 200
    assert mosaic.headers["content-type"].startswith("image/png")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/jpeg")

    task_after = migrated_client.get(f"/api/v1/tasks/{task_id}").json()
    assert task_after["progress"] == 28
    assert task_after["current_stage"] == "mosaic"

    events = migrated_client.get(f"/api/v1/jobs/{job_id}/events").text
    assert "event: job.started" in events
    assert "event: job.progress" in events
    assert "event: job.step" in events
    assert "event: job.succeeded" in events

    changed = migrated_client.post(
        f"/api/v1/tasks/{task_id}/images",
        files={"files": ("c.png", _png("blue"), "image/png")},
    )
    assert changed.status_code == 201
    assert migrated_client.get(f"/api/v1/tasks/{task_id}").json()["progress"] == 14
    # Historical artifacts remain auditable/downloadable after becoming stale.
    assert migrated_client.get(f"/api/v1/artifacts/{mosaic_id}/content").status_code == 200

    next_job = migrated_client.post(
        f"/api/v1/tasks/{task_id}/mosaic-jobs", json={"provider": "auto"}
    )
    assert next_job.status_code == 202
    assert next_job.json()["job"]["id"] != job_id
    assert run_worker(once=True, settings=test_settings) == 0
    assert (
        migrated_client.get(
            f"/api/v1/jobs/{next_job.json()['job']['id']}"
        ).json()["job"]["status"]
        == "succeeded"
    )
