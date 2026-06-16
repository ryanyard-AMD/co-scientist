import json
import uuid
from datetime import datetime, timezone

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.evidence import EvidenceRecord


def _create_goal(client):
    return client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()


def _seed_evidence(db, workspace_id, method_families, metric_names=None,
                   hardware=None, failure_modes=None, strength="weak"):
    now = datetime.now(timezone.utc)
    rec = EvidenceRecord(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        scout_run_id="sr-test",
        query_text="test query",
        paper_id=f"paper-{uuid.uuid4().hex[:8]}",
        title="Test Paper",
        chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
        chunk_index=0,
        chunk_text="Acoustic contrast control for personal sound zones.",
        score=0.9,
        method_families=json.dumps(method_families),
        metric_names=json.dumps(metric_names or []),
        hardware_assumptions=json.dumps(hardware or []),
        failure_modes=json.dumps(failure_modes or []),
        is_primary_method=True,
        evidence_strength=strength,
        created_at=now,
    )
    db.add(rec)
    db.commit()
    return rec


def _generate_and_review(client, db_session, goal_id):
    resp = client.post(f"/co-scientist/goals/{goal_id}/approaches/generate", json={})
    approaches = resp.json()["approaches"]
    for a in approaches:
        client.post(
            f"/co-scientist/goals/{goal_id}/approaches/{a['id']}/transition",
            json={"status": "reviewed"},
        )
    return approaches


def test_score_approach_returns_201(client, db_session):
    goal = _create_goal(client)
    _seed_evidence(db_session, goal["id"], ["beamforming"], metric_names=["acoustic_contrast_db"])
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    approaches = _generate_and_review(client, db_session, goal["id"])

    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/approaches/{approaches[0]['id']}/score",
        json={},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["dimensions"]) == 10
    assert "final_score" in body
    assert "risk_penalty" in body


def test_score_approach_not_found(client):
    goal = _create_goal(client)
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/approaches/nonexistent/score",
        json={},
    )
    assert resp.status_code == 404


def test_get_scores(client, db_session):
    goal = _create_goal(client)
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    approaches = _generate_and_review(client, db_session, goal["id"])

    client.post(
        f"/co-scientist/goals/{goal['id']}/approaches/{approaches[0]['id']}/score",
        json={},
    )
    resp = client.get(
        f"/co-scientist/goals/{goal['id']}/approaches/{approaches[0]['id']}/scores",
    )
    assert resp.status_code == 200
    assert len(resp.json()["dimensions"]) == 10


def test_get_scores_not_scored_returns_404(client, db_session):
    goal = _create_goal(client)
    created = client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF", "method_family": "beamforming",
    }).json()
    resp = client.get(
        f"/co-scientist/goals/{goal['id']}/approaches/{created['id']}/scores",
    )
    assert resp.status_code == 404


def test_score_all_returns_201(client, db_session):
    goal = _create_goal(client)
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    _seed_evidence(db_session, goal["id"], ["pressure_matching"])
    _seed_evidence(db_session, goal["id"], ["pressure_matching"])
    _generate_and_review(client, db_session, goal["id"])

    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/approaches/score-all",
        json={},
    )
    assert resp.status_code == 201
    assert len(resp.json()) == 2


def test_comparison_endpoint(client, db_session):
    goal = _create_goal(client)
    _seed_evidence(db_session, goal["id"], ["beamforming"], strength="strong")
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    _seed_evidence(db_session, goal["id"], ["pressure_matching"])
    _seed_evidence(db_session, goal["id"], ["pressure_matching"])
    _generate_and_review(client, db_session, goal["id"])
    client.post(f"/co-scientist/goals/{goal['id']}/approaches/score-all", json={})

    resp = client.get(f"/co-scientist/goals/{goal['id']}/approaches/comparison")
    assert resp.status_code == 200
    body = resp.json()
    assert "approaches" in body
    assert "dimension_rankings" in body
    assert len(body["dimension_rankings"]) == 10


def test_pareto_endpoint(client, db_session):
    goal = _create_goal(client)
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    _generate_and_review(client, db_session, goal["id"])
    client.post(f"/co-scientist/goals/{goal['id']}/approaches/score-all", json={})

    resp = client.get(f"/co-scientist/goals/{goal['id']}/approaches/pareto")
    assert resp.status_code == 200
    body = resp.json()
    assert "pareto_optimal" in body
    assert "dominated" in body
    assert len(body["pareto_optimal"]) == 1


def test_rescore_endpoint(client, db_session):
    goal = _create_goal(client)
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    approaches = _generate_and_review(client, db_session, goal["id"])

    client.post(
        f"/co-scientist/goals/{goal['id']}/approaches/{approaches[0]['id']}/score",
        json={},
    )
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/approaches/{approaches[0]['id']}/rescore",
        json={"weight_profile": "scientific_novelty"},
    )
    assert resp.status_code == 200
    body = resp.json()
    ev_dim = next(d for d in body["dimensions"] if d["dimension"] == "evidence_strength")
    assert ev_dim["weight"] == 0.22


def test_score_goal_not_found(client):
    resp = client.post("/co-scientist/goals/nonexistent/approaches/score-all", json={})
    assert resp.status_code == 404
