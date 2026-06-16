import pytest

from conftest import GOAL_PAYLOAD, MockRetrievalClient


@pytest.fixture(autouse=True)
def _patch_retrieval_client(monkeypatch):
    mock = MockRetrievalClient()
    monkeypatch.setattr(
        "coscientist.services.scout.RetrievalClient",
        lambda **kwargs: mock,
    )


def _create_goal(client):
    resp = client.post("/co-scientist/goals", json=GOAL_PAYLOAD)
    assert resp.status_code == 201
    return resp.json()


def test_post_scout_returns_201(client):
    goal = _create_goal(client)
    resp = client.post(f"/co-scientist/goals/{goal['id']}/scout", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert body["goal_id"] == goal["id"]
    assert body["evidence_count"] >= 1
    assert "groups" in body
    assert "summary" in body


def test_post_scout_goal_not_found(client):
    resp = client.post("/co-scientist/goals/nonexistent/scout", json={})
    assert resp.status_code == 404


def test_get_evidence_after_scout(client):
    goal = _create_goal(client)
    client.post(f"/co-scientist/goals/{goal['id']}/scout", json={})
    resp = client.get(f"/co-scientist/goals/{goal['id']}/scout/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert len(body["items"]) >= 1


def test_get_evidence_groups(client):
    goal = _create_goal(client)
    client.post(f"/co-scientist/goals/{goal['id']}/scout", json={})
    resp = client.get(
        f"/co-scientist/goals/{goal['id']}/scout/evidence/groups",
        params={"group_by": "method_family"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "groups" in body
    assert body["total_groups"] >= 1


def test_get_evidence_summary(client):
    goal = _create_goal(client)
    client.post(f"/co-scientist/goals/{goal['id']}/scout", json={})
    resp = client.get(f"/co-scientist/goals/{goal['id']}/scout/evidence/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_evidence"] >= 1
    assert "warnings" in body


def test_get_evidence_by_id(client):
    goal = _create_goal(client)
    client.post(f"/co-scientist/goals/{goal['id']}/scout", json={})
    list_resp = client.get(f"/co-scientist/goals/{goal['id']}/scout/evidence")
    evidence_id = list_resp.json()["items"][0]["id"]
    resp = client.get(f"/co-scientist/goals/{goal['id']}/scout/evidence/{evidence_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == evidence_id


def test_get_evidence_by_id_not_found(client):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/scout/evidence/nonexistent")
    assert resp.status_code == 404


def test_post_scout_with_method_filter(client):
    goal = _create_goal(client)
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/scout",
        json={"method_families": ["acoustic_contrast_control"]},
    )
    assert resp.status_code == 201
