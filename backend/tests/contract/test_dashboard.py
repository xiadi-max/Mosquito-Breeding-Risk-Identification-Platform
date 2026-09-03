from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image as PILImage


EXPECTED_TOP_LEVEL = {"meta", "tasks", "demoImages", "rois", "model", "risk"}


@pytest.mark.contract
def test_empty_dashboard_keeps_test_data_top_level_contract(migrated_client) -> None:
    response = migrated_client.get("/api/mosquito-workbench/dashboard")

    assert response.status_code == 200
    assert set(response.json()) == EXPECTED_TOP_LEVEL
    assert response.json()["tasks"] == []
    assert response.json()["demoImages"] == []
    assert response.json()["model"] == {
        "completedTargetCount": 0,
        "reviews": [],
        "provider": "fake",
        "activeVersion": None,
    }


@pytest.mark.contract
def test_dashboard_maps_current_task_and_images(migrated_client) -> None:
    task_response = migrated_client.post(
        "/api/v1/tasks",
        json={
            "name": "Dashboard 联调任务",
            "area": "联调区域",
            "survey_date": "2026-08-10",
            "task_type": "重点区域排查",
        },
    )
    task_id = task_response.json()["id"]
    image_buffer = BytesIO()
    PILImage.new("RGB", (16, 16), "green").save(image_buffer, format="JPEG")
    migrated_client.post(
        f"/api/v1/tasks/{task_id}/images",
        files={"files": ("demo.jpg", image_buffer.getvalue(), "image/jpeg")},
    )

    response = migrated_client.get(
        "/api/mosquito-workbench/dashboard", params={"task_id": task_id}
    )
    payload = response.json()

    assert response.status_code == 200
    assert set(payload) == EXPECTED_TOP_LEVEL
    assert payload["meta"]["current_task_id"] == task_id
    assert payload["tasks"][0]["uuid"] == task_id
    assert payload["tasks"][0]["progress"] == 14
    assert payload["tasks"][0]["summary"] == "1 张影像"
    assert payload["tasks"][0]["selected"] is True
    assert payload["demoImages"][0]["name"] == "demo.jpg"
    assert payload["rois"] == []
    assert payload["risk"]["highThreshold"] == 75
