from conftest import GOAL_PAYLOAD


def _create_goal(client):
    return client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()


def _payload(**overrides):
    data = {
        "target_type": "approach",
        "target_id": "approach-1",
        "is_positive": True,
    }
    data.update(overrides)
    return data


def test_add_feedback_returns_201(client):
    goal = _create_goal(client)
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/feedback",
        json=_payload(comment="great", reviewer_id="bob"),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_positive"] is True
    assert body["comment"] == "great"
    assert body["reviewer_id"] == "bob"
    assert body["workspace_id"] == goal["id"]


def test_add_feedback_unknown_goal_404(client):
    resp = client.post("/co-scientist/goals/nope/feedback", json=_payload())
    assert resp.status_code == 404


def test_list_feedback(client):
    goal = _create_goal(client)
    client.post(f"/co-scientist/goals/{goal['id']}/feedback", json=_payload(is_positive=True))
    client.post(f"/co-scientist/goals/{goal['id']}/feedback", json=_payload(is_positive=False))
    resp = client.get(f"/co-scientist/goals/{goal['id']}/feedback")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_list_feedback_filters_by_target(client):
    goal = _create_goal(client)
    client.post(
        f"/co-scientist/goals/{goal['id']}/feedback",
        json=_payload(target_type="experiment", target_id="exp-1"),
    )
    client.post(f"/co-scientist/goals/{goal['id']}/feedback", json=_payload())
    resp = client.get(
        f"/co-scientist/goals/{goal['id']}/feedback",
        params={"target_type": "experiment"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["target_type"] == "experiment"
