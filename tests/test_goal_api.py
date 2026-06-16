import pytest

GOAL_PAYLOAD = {
    "name": "PSZ Headphone",
    "description": "Personal sound zone for headphone form factor",
    "target_application": "personal_sound_zones",
    "success_criteria": [
        {"name": "acoustic_contrast", "operator": ">=", "target": 20.0, "unit": "dB"},
        {"name": "latency", "operator": "<=", "target": 10.0, "unit": "ms"},
    ],
    "device_constraints": {
        "speaker_count": 2,
        "form_factor": "headphone",
        "compute_budget": "low",
        "setup_time_minutes": 5,
    },
}


def test_create_goal_returns_201(client):
    resp = client.post("/co-scientist/goals", json=GOAL_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "PSZ Headphone"
    assert body["status"] == "draft"
    assert body["workspace_id"] == body["id"]


def test_create_goal_sets_workspace_id_equal_to_id(client):
    resp = client.post("/co-scientist/goals", json=GOAL_PAYLOAD)
    body = resp.json()
    assert body["workspace_id"] == body["id"]


def test_list_goals_empty(client):
    resp = client.get("/co-scientist/goals")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


def test_list_goals_returns_created(client):
    client.post("/co-scientist/goals", json=GOAL_PAYLOAD)
    resp = client.get("/co-scientist/goals")
    assert resp.json()["total"] == 1


def test_list_goals_filter_by_status(client):
    client.post("/co-scientist/goals", json=GOAL_PAYLOAD)
    resp = client.get("/co-scientist/goals?status=active")
    assert resp.json()["total"] == 0
    resp = client.get("/co-scientist/goals?status=draft")
    assert resp.json()["total"] == 1


def test_get_goal_by_id(client):
    created = client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()
    resp = client.get(f"/co-scientist/goals/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_goal_not_found(client):
    resp = client.get("/co-scientist/goals/nonexistent-id")
    assert resp.status_code == 404


def test_patch_goal(client):
    created = client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()
    resp = client.patch(
        f"/co-scientist/goals/{created['id']}",
        json={"name": "Updated Name"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


def test_transition_draft_to_active(client):
    created = client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()
    resp = client.post(
        f"/co-scientist/goals/{created['id']}/transition",
        json={"status": "active"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_transition_active_to_archived(client):
    created = client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()
    client.post(f"/co-scientist/goals/{created['id']}/transition", json={"status": "active"})
    resp = client.post(
        f"/co-scientist/goals/{created['id']}/transition",
        json={"status": "archived"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


def test_transition_invalid_raises_422(client):
    created = client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()
    # archived is terminal — can't go anywhere from archived
    client.post(f"/co-scientist/goals/{created['id']}/transition", json={"status": "archived"})
    resp = client.post(
        f"/co-scientist/goals/{created['id']}/transition",
        json={"status": "active"},
    )
    assert resp.status_code == 422


def test_transition_draft_to_draft_invalid(client):
    created = client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()
    resp = client.post(
        f"/co-scientist/goals/{created['id']}/transition",
        json={"status": "draft"},
    )
    assert resp.status_code == 422


def test_delete_draft_goal(client):
    created = client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()
    resp = client.delete(f"/co-scientist/goals/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/co-scientist/goals/{created['id']}").status_code == 404


def test_delete_active_goal_raises_409(client):
    created = client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()
    client.post(f"/co-scientist/goals/{created['id']}/transition", json={"status": "active"})
    resp = client.delete(f"/co-scientist/goals/{created['id']}")
    assert resp.status_code == 409


def test_health_endpoint(client):
    resp = client.get("/co-scientist/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
