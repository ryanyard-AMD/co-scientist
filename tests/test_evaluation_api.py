import json
import uuid

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.experiment import ExperimentCard

PREFIX = "/co-scientist"


def _create_goal(client):
    return client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()


def _seed_approach(db, workspace_id, status="reviewed"):
    card = ApproachCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="ACC",
        method_family="acoustic_contrast_control",
        domain="personal_sound_zones",
        problem_fit="Maximizes contrast.",
        mechanism_summary="Optimizes signals.",
        key_assumptions=json.dumps(["free-field"]),
        reported_metrics=json.dumps([]),
        hardware_requirements=json.dumps(["array"]),
        device_relevance="Headphone friendly.",
        risks_and_limitations=json.dumps([]),
        unresolved_questions=json.dumps([]),
        suggested_experiments=json.dumps([]),
        evidence_links=json.dumps(
            [{"evidence_id": "e1", "evidence_type": "direct", "claim_field": "mechanism_summary"}]
        ),
        status=status,
        maturity="theoretical",
    )
    db.add(card)
    db.commit()
    return card


def _seed_experiment(db, workspace_id, status="approved"):
    card = ExperimentCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="Sweep",
        objective="Measure contrast",
        hypothesis_text="Higher order increases contrast.",
        approach_ids=json.dumps([]),
        baseline_methods=json.dumps([]),
        independent_variables=json.dumps({"filter_order": [4, 8]}),
        fixed_assumptions=json.dumps({}),
        metrics=json.dumps(["acoustic_contrast"]),
        validation=json.dumps({"pass_conditions": {"acoustic_contrast": 20.0}}),
        runtime=json.dumps({}),
        artifacts=json.dumps([]),
        estimated_cost="low",
        estimated_runtime="medium",
        experiment_type="simulation",
        parameter_sweep_count=2,
        status=status,
    )
    db.add(card)
    db.commit()
    return card


def test_report_endpoint(client, db_session):
    goal = _create_goal(client)
    _seed_approach(db_session, goal["id"])
    _seed_experiment(db_session, goal["id"])
    resp = client.get(f"{PREFIX}/goals/{goal['id']}/evaluation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["goal_id"] == goal["id"]
    assert body["approach_usefulness"]["total"] == 1
    assert body["evidence_grounding"]["total_claims"] >= 1
    assert body["experiment_quality"]["total"] == 1


def test_approach_usefulness_endpoint(client, db_session):
    goal = _create_goal(client)
    _seed_approach(db_session, goal["id"], status="reviewed")
    _seed_approach(db_session, goal["id"], status="superseded")
    resp = client.get(f"{PREFIX}/goals/{goal['id']}/evaluation/approach-usefulness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["useful_count"] == 1
    assert body["discarded_count"] == 1
    assert body["usefulness_rate"] == 0.5


def test_evidence_grounding_endpoint(client, db_session):
    goal = _create_goal(client)
    _seed_approach(db_session, goal["id"])
    resp = client.get(f"{PREFIX}/goals/{goal['id']}/evaluation/evidence-grounding")
    assert resp.status_code == 200
    body = resp.json()
    assert body["grounded"] == 1
    assert "unsupported_claims" in body


def test_experiment_quality_endpoint(client, db_session):
    goal = _create_goal(client)
    _seed_experiment(db_session, goal["id"], status="approved")
    resp = client.get(f"{PREFIX}/goals/{goal['id']}/evaluation/experiment-quality")
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted_count"] == 1
    assert body["valid_count"] == 1


def test_unknown_goal_returns_404(client):
    resp = client.get(f"{PREFIX}/goals/does-not-exist/evaluation")
    assert resp.status_code == 404
