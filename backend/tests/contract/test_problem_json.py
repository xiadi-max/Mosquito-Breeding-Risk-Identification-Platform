import pytest


@pytest.mark.contract
def test_unknown_endpoint_uses_problem_json(client) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["status"] == 404
    assert payload["code"] == "NOT_FOUND"
    assert payload["request_id"] == response.headers["x-request-id"]
    assert payload["instance"] == "/api/v1/does-not-exist"


@pytest.mark.contract
def test_openapi_contains_m0_endpoints(client) -> None:
    response = client.get("/openapi.json")
    paths = response.json()["paths"]

    assert "/api/v1/health/live" in paths
    assert "/api/v1/health/ready" in paths
    assert "/api/v1/version" in paths
    assert "/api/v1/tasks" in paths
    assert "/api/v1/tasks/{task_id}/images" in paths
    assert "/api/v1/artifacts/{artifact_id}/content" in paths
    assert "/api/mosquito-workbench/dashboard" in paths
    assert "/api/v1/tasks/{task_id}/rois" in paths
    assert "/api/v1/tasks/{task_id}/grid-plans/preview" in paths
    assert "/api/v1/tasks/{task_id}/grid-plan" in paths
    assert "/api/v1/tasks/{task_id}/mosaic-jobs" in paths
    assert "/api/v1/jobs/{job_id}" in paths
    assert "/api/v1/jobs/{job_id}/events" in paths


@pytest.mark.contract
def test_cors_preflight_also_has_request_id(client) -> None:
    response = client.options(
        "/api/v1/tasks",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["x-request-id"].startswith("req_")
