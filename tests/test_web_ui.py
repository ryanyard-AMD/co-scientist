import json
import uuid

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.experiment import ExperimentCard
from coscientist.models.hypothesis import HypothesisCard
from coscientist.schemas.execution import RunRequestStatusEnum
from coscientist.services import execution as execution_svc
from coscientist.services import score as score_svc
from test_approval_api import _create_scored_approach


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


def _seed_hypothesis(db, workspace_id, name="ACC + PM", status="generated"):
    card = HypothesisCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name=name,
        text="Combine Acoustic Contrast Control and Pressure Matching.",
        rationale="Share hardware: dsp, loudspeaker array, microphone.",
        hypothesis_type="conservative",
        approach_ids=json.dumps([str(uuid.uuid4()), str(uuid.uuid4())]),
        assumptions=json.dumps(["free-field propagation"]),
        expected_benefits=json.dumps(["broader coverage"]),
        failure_modes=json.dumps(["device-geometry mismatch"]),
        required_experiments=json.dumps(["Validate combined approach"]),
        compatibility_notes=json.dumps([{
            "approach_a_id": "a1", "approach_b_id": "a2", "compatible": True,
            "shared_hardware": ["dsp", "loudspeaker array"],
            "conflicting_assumptions": [], "complementary_dimensions": [],
            "ontology_related": True, "note": "related in the ontology",
        }]),
        has_conflicts=False,
        status=status,
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
    for label in ("evidence", "approaches", "hypotheses", "experiments", "roadmap"):
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


def test_approaches_list_hides_superseded_by_default(client, db_session):
    goal = _create_goal(client)
    _seed_approach(db_session, goal["id"], name="Live Card", status="generated")
    _seed_approach(db_session, goal["id"], name="Old Card", status="superseded")
    resp = client.get(f"/ui/goals/{goal['id']}/approaches")
    assert resp.status_code == 200
    assert "Live Card" in resp.text
    assert "Old Card" not in resp.text
    assert "Show 1 superseded" in resp.text


def test_approaches_list_show_superseded_toggle(client, db_session):
    goal = _create_goal(client)
    _seed_approach(db_session, goal["id"], name="Live Card", status="generated")
    _seed_approach(db_session, goal["id"], name="Old Card", status="superseded")
    resp = client.get(f"/ui/goals/{goal['id']}/approaches?show_superseded=true")
    assert resp.status_code == 200
    assert "Live Card" in resp.text
    assert "Old Card" in resp.text
    assert "Hide superseded" in resp.text


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


# --- Hypotheses ---


def test_hypotheses_list_shows_seeded(client, db_session):
    goal = _create_goal(client)
    _seed_hypothesis(db_session, goal["id"])
    resp = client.get(f"/ui/goals/{goal['id']}/hypotheses")
    assert resp.status_code == 200
    assert "ACC + PM" in resp.text


def test_hypotheses_list_empty_ok(client):
    goal = _create_goal(client)
    resp = client.get(f"/ui/goals/{goal['id']}/hypotheses")
    assert resp.status_code == 200


def test_hypothesis_detail_shows_rationale_and_compat(client, db_session):
    goal = _create_goal(client)
    card = _seed_hypothesis(db_session, goal["id"])
    resp = client.get(f"/ui/goals/{goal['id']}/hypotheses/{card.id}")
    assert resp.status_code == 200
    assert "loudspeaker array" in resp.text
    assert "ontology-related" in resp.text


def test_hypothesis_detail_unknown_renders_error(client):
    goal = _create_goal(client)
    resp = client.get(f"/ui/goals/{goal['id']}/hypotheses/nope")
    assert resp.status_code == 404
    assert "Error 404" in resp.text


def test_hypothesis_review_sets_reviewed(client, db_session):
    goal = _create_goal(client)
    card = _seed_hypothesis(db_session, goal["id"])
    resp = client.post(f"/ui/goals/{goal['id']}/hypotheses/{card.id}/review")
    assert resp.status_code == 200
    db_session.expire_all()
    assert db_session.get(HypothesisCard, card.id).status == "reviewed"


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


def test_evaluation_page_ok(client, db_session):
    goal = _create_goal(client)
    _seed_approach(db_session, goal["id"])
    _seed_experiment(db_session, goal["id"])
    resp = client.get(f"/ui/goals/{goal['id']}/evaluation")
    assert resp.status_code == 200
    body = resp.text.lower()
    assert "grounding" in body
    assert "acceptance" in body


# --- Execution status UI (CS-EPIC-UI: CS-UI-008..013) ---


def _scored_experiment(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = client.post(
        f"/co-scientist/goals/{goal['id']}/experiments",
        json={
            "name": "Execution Experiment",
            "objective": "Evaluate method",
            "hypothesis_text": "Method achieves target",
            "approach_ids": [approach["id"]],
        },
    ).json()
    return goal, approach, exp


def _ingest(client, experiment_id, run_request_id, status="passed", **extra):
    body = {
        "result_bundle_id": f"rb-{run_request_id}",
        "run_request_id": run_request_id,
        "attempt_id": "1",
        "experiment_id": experiment_id,
        "validation_status": status,
        "metrics": {"acoustic_contrast": 22.0},
    }
    body.update(extra)
    return client.post("/co-scientist/result-bundles", json=body)


def test_experiment_detail_shows_execution_status_badge(client, db_session):
    # CS-UI-008: lifecycle state and execution status render as separate badges.
    goal = _create_goal(client)
    card = _seed_experiment(db_session, goal["id"])
    resp = client.get(f"/ui/goals/{goal['id']}/experiments/{card.id}")
    assert resp.status_code == 200
    assert "exec: not_submitted" in resp.text


def test_experiment_detail_shows_batch_panel(client, db_session):
    # CS-UI-009: ExecutionBatch panel with per-status run request counts.
    goal = _create_goal(client)
    card = _seed_experiment(db_session, goal["id"])
    batch = execution_svc.create_execution_batch(
        db_session,
        experiment_id=card.id,
        goal_id=goal["id"],
        workspace_id=goal["id"],
        submission_mode="run_request_batch",
    )
    execution_svc.register_run_request(
        db_session,
        run_request_id="rr-ui-1",
        experiment_id=card.id,
        goal_id=goal["id"],
        workspace_id=goal["id"],
        execution_batch_id=batch.id,
        status=RunRequestStatusEnum.running,
    )
    resp = client.get(f"/ui/goals/{goal['id']}/experiments/{card.id}")
    assert resp.status_code == 200
    assert batch.correlation_id in resp.text
    assert "rr-ui-1" in resp.text
    assert "Run requests" in resp.text


def test_experiment_detail_shows_score_provenance(client, db_session):
    # CS-UI-013: score panel shows before/after, rationale, and bundle links.
    goal, approach, exp = _scored_experiment(client, db_session)
    _ingest(client, exp["id"], "rr-1", status="passed")
    resp = client.get(f"/ui/goals/{goal['id']}/experiments/{exp['id']}")
    assert resp.status_code == 200
    assert "Score provenance" in resp.text
    assert "rb-rr-1" in resp.text


def test_validation_page_shows_execution_results(client, db_session):
    # CS-UI-010: ResultBundle summaries + aggregation appear in the validation view.
    goal, approach, exp = _scored_experiment(client, db_session)
    _ingest(client, exp["id"], "rr-1", status="passed")
    resp = client.get(f"/ui/goals/{goal['id']}/validation")
    assert resp.status_code == 200
    assert "Execution results" in resp.text
    assert "rb-rr-1" in resp.text
    assert "passed" in resp.text


def test_validation_page_marks_partial_batch(client, db_session):
    # CS-UI-011: partial batches are clearly flagged.
    goal, approach, exp = _scored_experiment(client, db_session)
    _ingest(client, exp["id"], "rr-1", status="failed", is_partial=True)
    resp = client.get(f"/ui/goals/{goal['id']}/validation")
    assert resp.status_code == 200
    assert "partial" in resp.text
