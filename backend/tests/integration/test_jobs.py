from __future__ import annotations

import re
from datetime import timedelta
from io import BytesIO

import pytest
from PIL import Image as PILImage

from app.core.db import create_db_engine, create_session_factory
from app.core.time import ensure_utc, utc_now
from app.domain.enums import JobStatus
from app.services.job_service import JobService


def _create_task_with_image(client) -> str:
    task = client.post(
        "/api/v1/tasks",
        json={
            "name": "Job 测试任务",
            "area": "测试区域",
            "survey_date": "2026-08-11",
            "task_type": "例行巡查",
        },
    ).json()
    image_buffer = BytesIO()
    PILImage.new("RGB", (24, 16), "blue").save(image_buffer, format="PNG")
    uploaded = client.post(
        f"/api/v1/tasks/{task['id']}/images",
        files={"files": ("job.png", image_buffer.getvalue(), "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    return task["id"]


@pytest.mark.integration
def test_opencv_job_requires_two_supported_images(migrated_client, test_settings) -> None:
    task_id = _create_task_with_image(migrated_client)
    opencv_settings = test_settings.model_copy(update={"mosaic_provider": "opencv"})
    migrated_client.app.state.settings = opencv_settings

    response = migrated_client.post(
        f"/api/v1/tasks/{task_id}/mosaic-jobs", json={"provider": "auto"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "MOSAIC_INPUT_INSUFFICIENT"


@pytest.mark.integration
def test_mosaic_job_idempotency_mutual_exclusion_cancel_and_sse(
    migrated_client,
) -> None:
    task_id = _create_task_with_image(migrated_client)
    body = {"provider": "auto", "options": {}}

    created = migrated_client.post(
        f"/api/v1/tasks/{task_id}/mosaic-jobs",
        headers={"Idempotency-Key": "mosaic-request-1"},
        json=body,
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job"]["id"]
    assert created.json()["job"]["status"] == "queued"

    replayed = migrated_client.post(
        f"/api/v1/tasks/{task_id}/mosaic-jobs",
        headers={"Idempotency-Key": "mosaic-request-1"},
        json=body,
    )
    assert replayed.status_code == 202
    assert replayed.json()["job"]["id"] == job_id
    assert replayed.headers["idempotency-replayed"] == "true"

    reused = migrated_client.post(
        f"/api/v1/tasks/{task_id}/mosaic-jobs",
        headers={"Idempotency-Key": "mosaic-request-1"},
        json={"provider": "fake", "options": {}},
    )
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

    competing = migrated_client.post(
        f"/api/v1/tasks/{task_id}/mosaic-jobs",
        headers={"Idempotency-Key": "mosaic-request-2"},
        json=body,
    )
    assert competing.status_code == 409
    assert competing.json()["code"] == "JOB_ALREADY_RUNNING"

    mutation = migrated_client.post(
        f"/api/v1/tasks/{task_id}/images",
        files={"files": ("blocked.png", b"not-read", "image/png")},
    )
    assert mutation.status_code == 409
    assert mutation.json()["code"] == "JOB_ALREADY_RUNNING"

    archive = migrated_client.post(
        f"/api/v1/tasks/{task_id}/archive", headers={"If-Match": '"2"'}
    )
    assert archive.status_code == 409
    assert archive.json()["code"] == "JOB_ALREADY_RUNNING"
    deletion = migrated_client.delete(f"/api/v1/tasks/{task_id}")
    assert deletion.status_code == 409
    assert deletion.json()["code"] == "JOB_ALREADY_RUNNING"

    canceled = migrated_client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["job"]["status"] == "canceled"

    events = migrated_client.get(f"/api/v1/jobs/{job_id}/events")
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "event: snapshot" in events.text
    assert "event: job.queued" in events.text
    assert "event: job.canceled" in events.text
    event_ids = [int(item) for item in re.findall(r"^id: (\d+)$", events.text, re.M)]
    assert len(event_ids) == 2

    resumed = migrated_client.get(
        f"/api/v1/jobs/{job_id}/events",
        headers={"Last-Event-ID": str(event_ids[0])},
    )
    assert f"id: {event_ids[0]}\n" not in resumed.text
    assert f"id: {event_ids[1]}\n" in resumed.text
    assert "event: job.canceled" in resumed.text


@pytest.mark.integration
def test_expired_job_lease_is_recovered_then_fails_at_attempt_limit(
    migrated_client, test_settings
) -> None:
    task_id = _create_task_with_image(migrated_client)
    created = migrated_client.post(
        f"/api/v1/tasks/{task_id}/mosaic-jobs", json={"provider": "auto"}
    ).json()
    job_id = created["job"]["id"]

    engine = create_db_engine(test_settings)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            service = JobService(session, test_settings)
            claimed = service.claim_next("worker-a")
            assert claimed and claimed.id == job_id
            service.mark_running(job_id, "worker-a")
            job = service.get_model(job_id)
            job.lease_expires_at = utc_now() - timedelta(seconds=1)
            job.max_attempts = 2
            session.commit()

        with factory() as session:
            assert JobService(session, test_settings).recover_expired() == 1
            recovered = JobService(session, test_settings).get_model(job_id)
            assert recovered.status == JobStatus.QUEUED.value
            assert recovered.attempt_count == 1

        with factory() as session:
            service = JobService(session, test_settings)
            claimed = service.claim_next("worker-b")
            assert claimed and claimed.attempt_count == 2
            service.mark_running(job_id, "worker-b")
            job = service.get_model(job_id)
            job.lease_expires_at = utc_now() - timedelta(seconds=1)
            session.commit()

        with factory() as session:
            assert JobService(session, test_settings).recover_expired() == 1
            failed = JobService(session, test_settings).get_model(job_id)
            assert failed.status == JobStatus.FAILED.value
            assert failed.error_code == "JOB_LEASE_EXPIRED"
    finally:
        engine.dispose()


@pytest.mark.integration
def test_job_heartbeat_retry_running_cancel_and_timeout(
    migrated_client, test_settings
) -> None:
    task_id = _create_task_with_image(migrated_client)
    job_id = migrated_client.post(
        f"/api/v1/tasks/{task_id}/mosaic-jobs",
        headers={"Idempotency-Key": "job-lifecycle"},
        json={"provider": "auto"},
    ).json()["job"]["id"]

    engine = create_db_engine(test_settings)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            service = JobService(session, test_settings)
            claimed = service.claim_next("worker-lifecycle")
            assert claimed and claimed.id == job_id
            running = service.mark_running(job_id, "worker-lifecycle")
            lease_before = running.lease_expires_at

        with factory() as session:
            service = JobService(session, test_settings)
            assert service.heartbeat(job_id, "worker-lifecycle") is True
            after = service.get_model(job_id)
            assert after.heartbeat_at is not None
            assert ensure_utc(after.lease_expires_at) >= ensure_utc(lease_before)
            retried = service.fail(
                job_id,
                "worker-lifecycle",
                code="TRANSIENT_TEST_ERROR",
                detail="retry me",
                retryable=True,
            )
            assert retried.status == JobStatus.QUEUED.value
            assert retried.current_step == "retry_wait"
            retried.available_at = utc_now()
            session.commit()

        with factory() as session:
            service = JobService(session, test_settings)
            claimed = service.claim_next("worker-cancel")
            assert claimed and claimed.attempt_count == 2
            service.mark_running(job_id, "worker-cancel")

        requested = migrated_client.post(f"/api/v1/jobs/{job_id}/cancel")
        assert requested.status_code == 200
        assert requested.json()["job"]["status"] == JobStatus.RUNNING.value
        assert requested.json()["job"]["cancel_requested_at"] is not None

        with factory() as session:
            service = JobService(session, test_settings)
            canceled = service.mark_canceled(job_id, "worker-cancel", "safe point")
            assert canceled.status == JobStatus.CANCELED.value

        timeout_job_id = migrated_client.post(
            f"/api/v1/tasks/{task_id}/mosaic-jobs",
            headers={"Idempotency-Key": "job-timeout"},
            json={"provider": "auto"},
        ).json()["job"]["id"]
        with factory() as session:
            service = JobService(session, test_settings)
            claimed = service.claim_next("worker-timeout")
            assert claimed and claimed.id == timeout_job_id
            service.mark_running(timeout_job_id, "worker-timeout")
            timeout_job = service.get_model(timeout_job_id)
            timeout_job.started_at = utc_now() - timedelta(
                seconds=test_settings.mosaic_job_timeout_seconds + 1
            )
            timeout_job.lease_expires_at = utc_now() + timedelta(seconds=60)
            session.commit()

        with factory() as session:
            service = JobService(session, test_settings)
            assert service.recover_expired() == 1
            timed_out = service.get_model(timeout_job_id)
            assert timed_out.status == JobStatus.FAILED.value
            assert timed_out.error_code == "JOB_TIMEOUT"
    finally:
        engine.dispose()


@pytest.mark.integration
def test_invalid_last_event_id_is_problem_json(migrated_client) -> None:
    task_id = _create_task_with_image(migrated_client)
    job_id = migrated_client.post(
        f"/api/v1/tasks/{task_id}/mosaic-jobs", json={"provider": "auto"}
    ).json()["job"]["id"]
    response = migrated_client.get(
        f"/api/v1/jobs/{job_id}/events", headers={"Last-Event-ID": "bad"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
