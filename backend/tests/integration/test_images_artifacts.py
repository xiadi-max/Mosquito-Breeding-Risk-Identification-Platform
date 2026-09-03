from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image as PILImage


TASK_PAYLOAD = {
    "name": "影像上传测试",
    "area": "测试区域",
    "survey_date": "2026-08-10",
    "task_type": "例行巡查",
}


def create_task(client, name: str = "影像上传测试") -> str:
    response = client.post("/api/v1/tasks", json={**TASK_PAYLOAD, "name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def image_bytes(image_format: str = "JPEG", color=(25, 80, 120)) -> bytes:
    buffer = BytesIO()
    PILImage.new("RGB", (32, 24), color).save(buffer, format=image_format)
    return buffer.getvalue()


def mpo_bytes() -> bytes:
    buffer = BytesIO()
    primary = PILImage.new("RGB", (32, 24), (25, 80, 120))
    auxiliary = PILImage.new("RGB", (32, 24), (120, 80, 25))
    primary.save(
        buffer,
        format="MPO",
        save_all=True,
        append_images=[auxiliary],
    )
    return buffer.getvalue()


@pytest.mark.integration
def test_upload_list_duplicate_download_range_etag_and_delete(migrated_client) -> None:
    task_id = create_task(migrated_client)
    jpeg = image_bytes()

    uploaded = migrated_client.post(
        f"/api/v1/tasks/{task_id}/images",
        files={"files": ("../../航拍<script>.jpg", jpeg, "application/octet-stream")},
    )
    assert uploaded.status_code == 201, uploaded.text
    payload = uploaded.json()
    assert len(payload["accepted"]) == 1
    assert payload["rejected"] == []
    assert payload["accepted"][0]["mime_type"] == "image/jpeg"
    assert payload["accepted"][0]["width"] == 32
    assert payload["summary"]["image_count"] == 1
    image_id = payload["accepted"][0]["id"]
    artifact_id = payload["accepted"][0]["artifact_id"]

    duplicate = migrated_client.post(
        f"/api/v1/tasks/{task_id}/images",
        files={"files": ("another-name.png", jpeg, "image/png")},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["accepted"] == []
    assert len(duplicate.json()["duplicates"]) == 1

    listed = migrated_client.get(f"/api/v1/tasks/{task_id}/images")
    assert listed.status_code == 200
    assert listed.json()["summary"]["image_count"] == 1

    task = migrated_client.get(f"/api/v1/tasks/{task_id}").json()
    assert task["progress"] == 14
    assert task["current_stage"] == "image_ingest"

    content_url = f"/api/v1/artifacts/{artifact_id}/content"
    downloaded = migrated_client.get(content_url)
    assert downloaded.status_code == 200
    assert downloaded.content == jpeg
    assert downloaded.headers["content-type"].startswith("image/jpeg")
    assert downloaded.headers["content-disposition"].startswith("inline")
    assert "<script>" not in downloaded.headers["content-disposition"]
    etag = downloaded.headers["etag"]

    not_modified = migrated_client.get(content_url, headers={"If-None-Match": etag})
    assert not_modified.status_code == 304

    ranged = migrated_client.get(content_url, headers={"Range": "bytes=0-9"})
    assert ranged.status_code == 206
    assert ranged.content == jpeg[:10]

    deleted = migrated_client.delete(
        f"/api/v1/tasks/{task_id}/images/{image_id}"
    )
    assert deleted.status_code == 204
    assert migrated_client.get(content_url).status_code == 404
    assert migrated_client.get(f"/api/v1/tasks/{task_id}").json()["progress"] == 0


@pytest.mark.integration
def test_magic_bytes_drive_type_and_invalid_file_is_rejected(migrated_client) -> None:
    task_id = create_task(migrated_client)
    png = image_bytes("PNG")

    response = migrated_client.post(
        f"/api/v1/tasks/{task_id}/images",
        files=[
            ("files", ("wrong-extension.jpg", png, "image/jpeg")),
            ("files", ("fake.jpg", b"not really an image", "image/jpeg")),
        ],
    )

    assert response.status_code == 201
    assert response.json()["accepted"][0]["mime_type"] == "image/png"
    assert response.json()["rejected"][0]["code"] == "UNSUPPORTED_MEDIA_TYPE"


@pytest.mark.integration
def test_jpeg_signed_mpo_is_accepted_as_jpeg(migrated_client) -> None:
    task_id = create_task(migrated_client)

    response = migrated_client.post(
        f"/api/v1/tasks/{task_id}/images",
        files={"files": ("drone-photo.jpg", mpo_bytes(), "image/jpeg")},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["rejected"] == []
    assert len(payload["accepted"]) == 1
    assert payload["accepted"][0]["mime_type"] == "image/jpeg"
    assert payload["accepted"][0]["width"] == 32
    assert payload["accepted"][0]["height"] == 24


@pytest.mark.integration
def test_tiff_is_rejected_by_the_scans_input_contract(migrated_client) -> None:
    task_id = create_task(migrated_client)
    response = migrated_client.post(
        f"/api/v1/tasks/{task_id}/images",
        files={"files": ("legacy.tif", image_bytes("TIFF"), "image/tiff")},
    )
    assert response.status_code == 201
    assert response.json()["accepted"] == []
    assert response.json()["rejected"][0]["code"] == "UNSUPPORTED_MEDIA_TYPE"


@pytest.mark.integration
def test_images_are_strictly_isolated_by_task(migrated_client) -> None:
    first_task = create_task(migrated_client, "任务一")
    second_task = create_task(migrated_client, "任务二")
    uploaded = migrated_client.post(
        f"/api/v1/tasks/{first_task}/images",
        files={"files": ("one.jpg", image_bytes(), "image/jpeg")},
    ).json()
    image_id = uploaded["accepted"][0]["id"]

    response = migrated_client.delete(
        f"/api/v1/tasks/{second_task}/images/{image_id}"
    )
    assert response.status_code == 404
    assert response.json()["code"] == "IMAGE_NOT_FOUND"


@pytest.mark.integration
def test_unknown_artifact_uses_controlled_404(migrated_client) -> None:
    response = migrated_client.get(
        "/api/v1/artifacts/00000000-0000-0000-0000-000000000000/content"
    )
    assert response.status_code == 404
    assert response.json()["code"] == "ARTIFACT_NOT_FOUND"
