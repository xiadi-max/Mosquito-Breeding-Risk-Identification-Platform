from app.worker import run_worker
from tests.integration.test_images_artifacts import create_task, image_bytes


def test_prestitched_image_is_imported_without_running_stitcher(migrated_client, test_settings, monkeypatch):
    from app.adapters.mosaic.opencv import OpenCVMosaicEngine

    def forbidden(*args, **kwargs):
        raise AssertionError("A prestitched image must never run OpenCV stitching")

    monkeypatch.setattr(OpenCVMosaicEngine, "run", forbidden)
    task_id = create_task(migrated_client)
    original = image_bytes()
    uploaded = migrated_client.post(f"/api/v1/tasks/{task_id}/images",
        files={"files": ("prestitched.jpg", original, "image/jpeg")})
    assert uploaded.status_code == 201
    queued = migrated_client.post(f"/api/v1/tasks/{task_id}/mosaic-jobs", json={"provider":"imported"})
    assert queued.status_code == 202, queued.text
    # The worker must configure its own decoder guard, independently of the API.
    from PIL import Image
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    assert run_worker(once=True, settings=test_settings) == 0
    job = migrated_client.get(queued.json()["links"]["self"]).json()["job"]
    assert job["status"] == "succeeded", job
    result = job["result"]
    assert (result["width"], result["height"]) == (32, 24)
    content = migrated_client.get(f"/api/v1/artifacts/{result['mosaic_artifact_id']}/content")
    assert content.content == original
    task = migrated_client.get(f"/api/v1/tasks/{task_id}").json()
    assert task["current_stage"] == "mosaic"
