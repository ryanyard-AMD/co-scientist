import json
import uuid

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.experiment import ExperimentCard
from coscientist.services import score as score_svc


def _create_goal(client):
    return client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()


def _seed_approach(db, workspace_id, name="Acoustic Contrast Control", status="generated"):
    card = ApproachCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name=name,
        method_family="acoustic_contrast_control",
        domain="personal_sound_zones",
        problem_fit="Maximizes energy difference between bright and dark zones.",
        mechanism_summary="Optimizes loudspeaker signals to maximize acoustic contrast.",
        key_assumptions=json.dumps(["free-field propagation"]),
        reported_metrics=json.dumps([]),
        hardware_requirements=json.dumps(["loudspeaker array"]),
        device_relevance="Headphone form factor friendly.",
        risks_and_limitations=json.dumps([]),
        unresolved_questions=json.dumps([]),
        suggested_experiments=json.dumps([]),
        evidence_links=json.dumps(
            [{"evidence_id": "ev1", "evidence_type": "direct", "claim_field": "mechanism_summary"}]
        ),
        status=status,
        maturity="theoretical",
    )
    db.add(card)
    db.commit()
    return card


def _seed_experiment(db, workspace_id, name="Contrast sweep", objective="Measure contrast"):
    card = ExperimentCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name=name,
        objective=objective,
        hypothesis_text="Higher filter order increases contrast.",
        approach_ids=json.dumps([]),
        baseline_methods=json.dumps(["pressure_matching"]),
        independent_variables=json.dumps({"filter_order": [4, 8, 16]}),
        fixed_assumptions=json.dumps({}),
        metrics=json.dumps(["acoustic_contrast"]),
        validation=json.dumps({"pass_conditions": {"acoustic_contrast": 20.0}}),
        runtime=json.dumps({}),
        artifacts=json.dumps([]),
        estimated_cost="low",
        estimated_runtime="medium",
        experiment_type="simulation",
        parameter_sweep_count=3,
        status="generated",
    )
    db.add(card)
    db.commit()
    return card


# --- Dashboard / navigation (CS-UI-001) ---


def test_index_redirects_to_goals(client):
    resp = client.get("/ui/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui/goals"


def test_goals_page_lists_goal(client):
    goal = _create_goal(client)
    resp = client.get("/ui/goals")
    assert resp.status_code == 200
    assert goal["name"] in resp.text


def test_dashboard_shows_section_labels(client):
    goal = _create_goal(client)
    resp = client.get(f"/ui/goals/{goal['id']}")
    assert resp.status_code == 200
    body = resp.text.lower()
    for label in ("evidence", "approaches", "experiments", "roadmap"):
        assert label in body


def test_dashboard_unknown_goal_renders_error(client):
    resp = client.get("/ui/goals/does-not-exist")
    assert resp.status_code == 404
    assert "Error 404" in resp.text


# --- Approaches (CS-UI-002) ---


def test_approaches_list_shows_seeded(client, db_session):
    goal = _create_goal(client)
    _seed_approach(db_session, goal["id"])
    resp = client.get(f"/ui/goals/{goal['id']}/approaches")
    assert resp.status_code == 200
    assert "Acoustic Contrast Control" in resp.text


def test_approach_detail_shows_mechanism(client, db_session):
    goal = _create_goal(client)
    card = _seed_approach(db_session, goal["id"])
    resp = client.get(f"/ui/goals/{goal['id']}/approaches/{card.id}")
    assert resp.status_code == 200
    assert "maximize acoustic contrast" in resp.text


def test_approach_detail_unknown_renders_error(client):
    goal = _create_goal(client)
    resp = client.get(f"/ui/goals/{goal['id']}/approaches/nope")
    assert resp.status_code == 404
    assert "Error 404" in resp.text


def test_approve_action_sets_reviewed(client, db_session):
    goal = _create_goal(client)
    card = _seed_approach(db_session, goal["id"])
    resp = client.post(f"/ui/goals/{goal['id']}/approaches/{card.id}/review")
    assert resp.status_code == 200
    db_session.expire_all()
    assert db_session.get(ApproachCard, card.id).status == "reviewed"


def test_reject_action_sets_superseded(client, db_session):
    goal = _create_goal(client)
    card = _seed_approach(db_session, goal["id"])
    resp = client.post(f"/ui/goals/{goal['id']}/approaches/{card.id}/reject")
    assert resp.status_code == 200
    db_session.expire_all()
    assert db_session.get(ApproachCard, card.id).status == "superseded"


def test_edit_action_updates_name(client, db_session):
    goal = _create_goal(client)
    card = _seed_approach(db_session, goal["id"])
    resp = client.post(
        f"/ui/goals/{goal['id']}/approaches/{card.id}",
        data={"name": "Renamed ACC", "mechanism_summary": "new mechanism"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.expire_all()
    assert db_session.get(ApproachCard, card.id).name == "Renamed ACC"


def test_merge_action_supersedes_source(client, db_session):
    goal = _create_goal(client)
    source = _seed_approach(db_session, goal["id"], name="Source", status="reviewed")
    target = _seed_approach(db_session, goal["id"], name="Target", status="reviewed")
    resp = client.post(
        f"/ui/goals/{goal['id']}/approaches/merge",
        data={"source_approach_id": source.id, "target_approach_id": target.id},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.expire_all()
    assert db_session.get(ApproachCard, source.id).status == "superseded"


# --- Scoring (CS-UI-003) ---


def test_score_panel_before_scoring_shows_not_scored(client, db_session):
    goal = _create_goal(client)
    card = _seed_approach(db_session, goal["id"])
    resp = client.get(f"/ui/goals/{goal['id']}/approaches/{card.id}/score-panel")
    assert resp.status_code == 200
    assert "Not scored yet" in resp.text


def test_score_action_creates_scores(client, db_session):
    goal = _create_goal(client)
    card = _seed_approach(db_session, goal["id"], status="reviewed")
    resp = client.post(f"/ui/goals/{goal['id']}/approaches/{card.id}/score")
    assert resp.status_code == 200
    assert "evidence_strength" in resp.text
    scores = score_svc.get_scores(db_session, card.id)
    assert len(scores.dimensions) == 10


# --- Experiments (CS-UI-004) ---


def test_experiments_list_shows_seeded(client, db_session):
    goal = _create_goal(client)
    _seed_experiment(db_session, goal["id"])
    resp = client.get(f"/ui/goals/{goal['id']}/experiments")
    assert resp.status_code == 200
    assert "Contrast sweep" in resp.text


def test_experiment_detail_shows_objective(client, db_session):
    goal = _create_goal(client)
    card = _seed_experiment(db_session, goal["id"])
    resp = client.get(f"/ui/goals/{goal['id']}/experiments/{card.id}")
    assert resp.status_code == 200
    assert "Measure contrast" in resp.text


def test_experiment_edit_updates_objective(client, db_session):
    goal = _create_goal(client)
    card = _seed_experiment(db_session, goal["id"])
    resp = client.post(
        f"/ui/goals/{goal['id']}/experiments/{card.id}",
        data={
            "name": card.name,
            "objective": "New objective",
            "hypothesis_text": card.hypothesis_text,
            "metrics": "acoustic_contrast, latency",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.expire_all()
    assert db_session.get(ExperimentCard, card.id).objective == "New objective"


def test_experiment_export_yaml(client, db_session):
    goal = _create_goal(client)
    card = _seed_experiment(db_session, goal["id"])
    resp = client.get(
        f"/ui/goals/{goal['id']}/experiments/{card.id}/export", params={"fmt": "yaml"}
    )
    assert resp.status_code == 200
    assert "objective" in resp.text


# --- Read-only P1 views (CS-UI-005, 006, 007) ---


def test_validation_page_empty_ok(client):
    goal = _create_goal(client)
    resp = client.get(f"/ui/goals/{goal['id']}/validation")
    assert resp.status_code == 200


def test_devices_page_empty_ok(client):
    goal = _create_goal(client)
    resp = client.get(f"/ui/goals/{goal['id']}/devices")
    assert resp.status_code == 200


def test_roadmap_page_empty_ok(client):
    goal = _create_goal(client)
    resp = client.get(f"/ui/goals/{goal['id']}/roadmap")
    assert resp.status_code == 200


def test_evidence_page_ok(client):
    goal = _create_goal(client)
    resp = client.get(f"/ui/goals/{goal['id']}/evidence")
    assert resp.status_code == 200
