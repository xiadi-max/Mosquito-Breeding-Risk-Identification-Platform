from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.db import create_db_engine, create_session_factory
from app.domain.enums import ArtifactKind
from app.domain.models import Artifact, GridPlan, ROIVersion, Task
from app.worker import run_worker


def seed_task_and_mosaic(settings, *, width: int = 1000, height: int = 900) -> tuple[str, str]:
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    task_id = str(uuid4())
    mosaic_id = str(uuid4())
    now = datetime.now(UTC)
    with factory() as session:
        session.add(
            Task(
                id=task_id,
                code=f"T-20260813-{uuid4().hex[:4].upper()}",
                name="M3 ROI 网格测试",
                area="测试区",
                survey_date=now.date(),
                task_type="例行巡查",
                state="running",
                version=1,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Artifact(
                id=mosaic_id,
                task_id=task_id,
                kind=ArtifactKind.MOSAIC.value,
                relative_path=f"tasks/{task_id}/mosaic/test/mosaic.png",
                sha256="a" * 64,
                size_bytes=1,
                mime_type="image/png",
                width=width,
                height=height,
                metadata_json="{}",
                is_current=True,
                created_at=now,
            )
        )
        session.commit()
    engine.dispose()
    return task_id, mosaic_id


@pytest.mark.integration
def test_roi_versions_conflict_invalid_polygon_and_grid_worker(
    test_settings, migrated_client
) -> None:
    task_id, mosaic_id = seed_task_and_mosaic(test_settings)
    empty = migrated_client.get(f"/api/v1/tasks/{task_id}/rois")
    assert empty.status_code == 200
    assert empty.json()["version"] == 0

    saved = migrated_client.put(
        f"/api/v1/tasks/{task_id}/rois",
        json={
            "expected_version": 0,
            "source_artifact_id": mosaic_id,
            "coordinate_space": "mosaic_pixel",
            "items": [
                {
                    "code": "ROI-01",
                    "visible": True,
                    "polygon": [[0, 0], [1000, 0], [1000, 900], [0, 900]],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert saved.json()["items"][0]["area_px2"] == 900000
    assert "grid_plan" in saved.json()["invalidated"]

    conflict = migrated_client.put(
        f"/api/v1/tasks/{task_id}/rois",
        json={
            "expected_version": 0,
            "source_artifact_id": mosaic_id,
            "items": [],
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "VERSION_CONFLICT"

    invalid = migrated_client.put(
        f"/api/v1/tasks/{task_id}/rois",
        json={
            "expected_version": 1,
            "source_artifact_id": mosaic_id,
            "items": [
                {
                    "code": "ROI-X",
                    "polygon": [[0, 0], [100, 100], [0, 100], [100, 0]],
                }
            ],
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "INVALID_POLYGON"

    preview = migrated_client.post(
        f"/api/v1/tasks/{task_id}/grid-plans/preview",
        json={
            "roi_version": 1,
            "tile_size": 640,
            "overlap": 0.2,
            "edge_strategy": "pad",
            "min_roi_intersection": 0.1,
        },
    )
    assert preview.status_code == 200, preview.text
    preview_data = preview.json()
    assert preview_data["step_px"] == 512
    assert preview_data["count"] > 0
    assert preview_data["padded_count"] > 0

    queued = migrated_client.put(
        f"/api/v1/tasks/{task_id}/grid-plan",
        headers={"Idempotency-Key": "grid-m3-test"},
        json={
            "roi_version": 1,
            "tile_size": 640,
            "overlap": 0.2,
            "edge_strategy": "pad",
            "min_roi_intersection": 0.1,
            "fingerprint": preview_data["fingerprint"],
        },
    )
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["job"]["id"]

    replayed = migrated_client.put(
        f"/api/v1/tasks/{task_id}/grid-plan",
        headers={"Idempotency-Key": "grid-m3-test"},
        json={
            "roi_version": 1,
            "tile_size": 640,
            "overlap": 0.2,
            "edge_strategy": "pad",
            "min_roi_intersection": 0.1,
            "fingerprint": preview_data["fingerprint"],
        },
    )
    assert replayed.status_code == 202
    assert replayed.headers["Idempotency-Replayed"] == "true"
    assert replayed.json()["job"]["id"] == job_id

    assert run_worker(once=True, settings=test_settings) == 0
    job = migrated_client.get(f"/api/v1/jobs/{job_id}")
    assert job.json()["job"]["status"] == "succeeded"

    plan = migrated_client.get(f"/api/v1/tasks/{task_id}/grid-plan")
    assert plan.status_code == 200, plan.text
    assert plan.json()["count"] == preview_data["count"]
    assert len(plan.json()["tiles"]) == preview_data["count"]

    task = migrated_client.get(f"/api/v1/tasks/{task_id}")
    assert task.json()["progress"] == 57
    assert task.json()["current_stage"] == "grid"


@pytest.mark.integration
def test_roi_change_marks_current_grid_stale(test_settings, migrated_client) -> None:
    task_id, mosaic_id = seed_task_and_mosaic(test_settings)
    first_roi = {
        "expected_version": 0,
        "source_artifact_id": mosaic_id,
        "items": [{"code": "ROI-01", "polygon": [[0, 0], [900, 0], [900, 800], [0, 800]]}],
    }
    assert migrated_client.put(f"/api/v1/tasks/{task_id}/rois", json=first_roi).status_code == 200
    preview = migrated_client.post(
        f"/api/v1/tasks/{task_id}/grid-plans/preview",
        json={"roi_version": 1},
    ).json()
    queued = migrated_client.put(
        f"/api/v1/tasks/{task_id}/grid-plan",
        json={"roi_version": 1, "fingerprint": preview["fingerprint"]},
    )
    assert queued.status_code == 202
    assert run_worker(once=True, settings=test_settings) == 0

    second = migrated_client.put(
        f"/api/v1/tasks/{task_id}/rois",
        json={
            "expected_version": 1,
            "source_artifact_id": mosaic_id,
            "items": [{"code": "ROI-01", "polygon": [[50, 50], [800, 50], [800, 700], [50, 700]]}],
        },
    )
    assert second.status_code == 200
    assert migrated_client.get(f"/api/v1/tasks/{task_id}/grid-plan").status_code == 404

    engine = create_db_engine(test_settings)
    factory = create_session_factory(engine)
    with factory() as session:
        statuses = list(session.execute(select(GridPlan.status)).scalars())
        current_roi = session.execute(
            select(ROIVersion).where(ROIVersion.is_current.is_(True))
        ).scalar_one()
        assert statuses == ["stale"]
        assert current_roi.version == 2
    engine.dispose()
