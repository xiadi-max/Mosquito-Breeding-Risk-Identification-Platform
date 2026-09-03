from __future__ import annotations

import pytest


TASK_PAYLOAD = {
    "name": "棠下村 8 月雨后复查",
    "area": "棠下村东南片区",
    "survey_date": "2026-08-10",
    "task_type": "雨后复查",
}


def create_task(client, **overrides):
    payload = {**TASK_PAYLOAD, **overrides}
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response


@pytest.mark.integration
def test_task_crud_search_version_conflict_archive_and_delete(migrated_client) -> None:
    created_response = create_task(migrated_client)
    created = created_response.json()
    task_id = created["id"]

    assert created["code"].startswith("T-20260810-")
    assert created["progress"] == 0
    assert created["version"] == 1
    assert created_response.headers["location"] == f"/api/v1/tasks/{task_id}"
    assert created_response.headers["etag"] == '"1"'

    listed = migrated_client.get("/api/v1/tasks", params={"q": "雨后"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [task_id]

    fetched = migrated_client.get(f"/api/v1/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["current_stage"] == "task_created"

    updated = migrated_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers={"If-Match": '"1"'},
        json={"name": "棠下村雨后复查（更新）"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["name"] == "棠下村雨后复查（更新）"

    conflict = migrated_client.patch(
        f"/api/v1/tasks/{task_id}",
        headers={"If-Match": '"1"'},
        json={"area": "旧版本修改"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "VERSION_CONFLICT"

    archived = migrated_client.post(
        f"/api/v1/tasks/{task_id}/archive", headers={"If-Match": '"2"'}
    )
    assert archived.status_code == 200
    assert archived.json()["state"] == "archived"

    deleted = migrated_client.delete(f"/api/v1/tasks/{task_id}")
    assert deleted.status_code == 204
    assert migrated_client.get(f"/api/v1/tasks/{task_id}").status_code == 404


@pytest.mark.integration
def test_task_cursor_pagination_is_stable(migrated_client) -> None:
    first_id = create_task(migrated_client, name="任务 A").json()["id"]
    second_id = create_task(migrated_client, name="任务 B").json()["id"]

    first_page = migrated_client.get("/api/v1/tasks", params={"limit": 1})
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 1
    assert first_page.json()["next_cursor"]

    second_page = migrated_client.get(
        "/api/v1/tasks",
        params={"limit": 1, "cursor": first_page.json()["next_cursor"]},
    )
    assert second_page.status_code == 200
    ids = {
        first_page.json()["items"][0]["id"],
        second_page.json()["items"][0]["id"],
    }
    assert ids == {first_id, second_id}


@pytest.mark.integration
def test_task_update_requires_version(migrated_client) -> None:
    task_id = create_task(migrated_client).json()["id"]
    response = migrated_client.patch(
        f"/api/v1/tasks/{task_id}", json={"name": "没有版本号"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
