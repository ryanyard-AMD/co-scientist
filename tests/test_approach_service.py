import json
import uuid
from datetime import datetime, timezone

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.approach import (
    ApproachCardCreate,
    ApproachGenerateRequest,
    ApproachCardUpdate,
    ApproachMergeRequest,
    ApproachStatusEnum,
)
from coscientist.services import approach as svc
from coscientist.services import goal as goal_svc


def _create_goal(db):
    from coscientist.schemas.goal import GoalCreate, SuccessCriterion, DeviceConstraints
    data = GoalCreate(**GOAL_PAYLOAD)
    return goal_svc.create(db, data)


def _seed_evidence(db, workspace_id, method_families, metric_names=None,
                   hardware=None, failure_modes=None, text="test chunk text",
                   score=0.9, is_primary=True):
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
        chunk_text=text,
        score=score,
        method_families=json.dumps(method_families),
        metric_names=json.dumps(metric_names or []),
        hardware_assumptions=json.dumps(hardware or []),
        failure_modes=json.dumps(failure_modes or []),
        is_primary_method=is_primary,
        evidence_strength="weak",
        created_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def test_create_approach_card(db_session):
    goal = _create_goal(db_session)
    data = ApproachCardCreate(
        name="Beamforming",
        method_family="beamforming",
        mechanism_summary="Steers beams toward target zones",
    )
    result = svc.create(db_session, goal.id, data)
    assert result.name == "Beamforming"
    assert result.method_family == "beamforming"
    assert result.status == ApproachStatusEnum.generated
    assert result.workspace_id == goal.id


def test_create_validates_goal_exists(db_session):
    data = ApproachCardCreate(name="X", method_family="x")
    with pytest.raises(Exception) as exc_info:
        svc.create(db_session, "nonexistent", data)
    assert exc_info.value.status_code == 404


def test_get_approach(db_session):
    goal = _create_goal(db_session)
    created = svc.create(db_session, goal.id, ApproachCardCreate(name="BF", method_family="beamforming"))
    result = svc.get(db_session, created.id)
    assert result.id == created.id


def test_get_approach_not_found(db_session):
    with pytest.raises(Exception) as exc_info:
        svc.get(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


def test_list_approaches_empty(db_session):
    goal = _create_goal(db_session)
    items, total = svc.list_approaches(db_session, goal.id)
    assert total == 0
    assert items == []


def test_list_approaches_filter_status(db_session):
    goal = _create_goal(db_session)
    svc.create(db_session, goal.id, ApproachCardCreate(name="BF", method_family="beamforming"))
    items, total = svc.list_approaches(db_session, goal.id, status=ApproachStatusEnum.generated)
    assert total == 1
    items, total = svc.list_approaches(db_session, goal.id, status=ApproachStatusEnum.reviewed)
    assert total == 0


def test_list_approaches_filter_method(db_session):
    goal = _create_goal(db_session)
    svc.create(db_session, goal.id, ApproachCardCreate(name="BF", method_family="beamforming"))
    svc.create(db_session, goal.id, ApproachCardCreate(name="ACC", method_family="acc"))
    items, total = svc.list_approaches(db_session, goal.id, method_family="beamforming")
    assert total == 1
    assert items[0].method_family == "beamforming"


def test_update_approach(db_session):
    goal = _create_goal(db_session)
    created = svc.create(db_session, goal.id, ApproachCardCreate(name="BF", method_family="beamforming"))
    result = svc.update(db_session, created.id, ApproachCardUpdate(name="Updated BF"))
    assert result.name == "Updated BF"


def test_transition_generated_to_reviewed(db_session):
    goal = _create_goal(db_session)
    created = svc.create(db_session, goal.id, ApproachCardCreate(name="BF", method_family="beamforming"))
    result = svc.transition(db_session, created.id, ApproachStatusEnum.reviewed)
    assert result.status == ApproachStatusEnum.reviewed


def test_transition_reviewed_to_scored(db_session):
    goal = _create_goal(db_session)
    created = svc.create(db_session, goal.id, ApproachCardCreate(name="BF", method_family="beamforming"))
    svc.transition(db_session, created.id, ApproachStatusEnum.reviewed)
    result = svc.transition(db_session, created.id, ApproachStatusEnum.scored)
    assert result.status == ApproachStatusEnum.scored


def test_transition_superseded_is_terminal(db_session):
    goal = _create_goal(db_session)
    created = svc.create(db_session, goal.id, ApproachCardCreate(name="BF", method_family="beamforming"))
    svc.transition(db_session, created.id, ApproachStatusEnum.superseded)
    with pytest.raises(Exception) as exc_info:
        svc.transition(db_session, created.id, ApproachStatusEnum.reviewed)
    assert exc_info.value.status_code == 422


def test_transition_invalid_raises_422(db_session):
    goal = _create_goal(db_session)
    created = svc.create(db_session, goal.id, ApproachCardCreate(name="BF", method_family="beamforming"))
    with pytest.raises(Exception) as exc_info:
        svc.transition(db_session, created.id, ApproachStatusEnum.validated)
    assert exc_info.value.status_code == 422


def test_delete_generated_card(db_session):
    goal = _create_goal(db_session)
    created = svc.create(db_session, goal.id, ApproachCardCreate(name="BF", method_family="beamforming"))
    svc.delete(db_session, created.id)
    with pytest.raises(Exception) as exc_info:
        svc.get(db_session, created.id)
    assert exc_info.value.status_code == 404


def test_delete_reviewed_card_raises_409(db_session):
    goal = _create_goal(db_session)
    created = svc.create(db_session, goal.id, ApproachCardCreate(name="BF", method_family="beamforming"))
    svc.transition(db_session, created.id, ApproachStatusEnum.reviewed)
    with pytest.raises(Exception) as exc_info:
        svc.delete(db_session, created.id)
    assert exc_info.value.status_code == 409


def test_generate_approaches_from_evidence(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db"])
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["latency_ms"])
    _seed_evidence(db_session, goal.id, ["pressure_matching"])
    _seed_evidence(db_session, goal.id, ["pressure_matching"])

    result = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    assert result.approaches_created == 2
    names = {a.method_family for a in result.approaches}
    assert "beamforming" in names
    assert "pressure_matching" in names


def test_generate_approaches_skips_duplicates(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_evidence(db_session, goal.id, ["beamforming"])

    r1 = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    assert r1.approaches_created == 1

    r2 = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    assert r2.approaches_created == 0
    assert r2.approaches_skipped_duplicate == 1


def test_generate_approaches_min_evidence_threshold(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"])

    result = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest(min_evidence_count=2))
    assert result.approaches_created == 0


def test_generate_approaches_method_filter(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_evidence(db_session, goal.id, ["pressure_matching"])
    _seed_evidence(db_session, goal.id, ["pressure_matching"])

    result = svc.generate_approaches(
        db_session, goal.id,
        ApproachGenerateRequest(method_families=["beamforming"]),
    )
    assert result.approaches_created == 1
    assert result.approaches[0].method_family == "beamforming"


def test_generate_approaches_evidence_links_populated(db_session):
    goal = _create_goal(db_session)
    e1 = _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db"])
    e2 = _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["latency_ms"])

    result = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    card = result.approaches[0]
    evidence_ids = {el.evidence_id for el in card.evidence_links}
    assert e1.id in evidence_ids
    assert e2.id in evidence_ids


def test_generate_approaches_metrics_from_evidence(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db", "latency_ms"])
    _seed_evidence(db_session, goal.id, ["beamforming"])

    result = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    card = result.approaches[0]
    metric_names = {m.metric_name for m in card.reported_metrics}
    assert "acoustic_contrast_db" in metric_names
    assert "latency_ms" in metric_names


def test_generate_approaches_hardware_from_evidence(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], hardware=["loudspeaker_array", "microphone_array"])
    _seed_evidence(db_session, goal.id, ["beamforming"])

    result = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    card = result.approaches[0]
    assert "loudspeaker_array" in card.hardware_requirements
    assert "microphone_array" in card.hardware_requirements


def test_generate_approaches_risks_from_evidence(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], failure_modes=["head_movement", "room_reverberation"])
    _seed_evidence(db_session, goal.id, ["beamforming"])

    result = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    card = result.approaches[0]
    fm_names = {r.failure_mode for r in card.risks_and_limitations}
    assert "head_movement" in fm_names
    assert "room_reverberation" in fm_names


def test_generate_no_evidence_returns_empty(db_session):
    goal = _create_goal(db_session)
    result = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    assert result.approaches_created == 0
    assert result.approaches == []


def test_find_duplicates(db_session):
    goal = _create_goal(db_session)
    svc.create(db_session, goal.id, ApproachCardCreate(name="BF1", method_family="beamforming"))
    svc.create(db_session, goal.id, ApproachCardCreate(name="BF2", method_family="beamforming"))
    warnings = svc.find_duplicates(db_session, goal.id)
    assert len(warnings) == 2
    assert all(w.method_family == "beamforming" for w in warnings)


def test_merge_approaches(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db"])
    _seed_evidence(db_session, goal.id, ["beamforming"])

    r = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    target = r.approaches[0]

    source = svc.create(db_session, goal.id, ApproachCardCreate(
        name="BF Manual",
        method_family="beamforming",
        hardware_requirements=["headrest_speaker_array"],
        unresolved_questions=["How does it scale?"],
    ))

    result = svc.merge_approaches(db_session, ApproachMergeRequest(
        source_approach_id=source.id,
        target_approach_id=target.id,
    ))
    assert "headrest_speaker_array" in result.hardware_requirements
    assert "How does it scale?" in result.unresolved_questions

    merged_source = svc.get(db_session, source.id)
    assert merged_source.status == ApproachStatusEnum.superseded
    assert merged_source.merged_into_id == target.id


def _seed_synthesis(db, workspace_id, method_family, *, synthesis_text="Synthesized mechanism.",
                    cited_evidence_ids=None, reported_metrics=None, hardware=None,
                    failure_modes=None, open_questions=None, scout_run_id="sr-test"):
    from coscientist.models.synthesis import EvidenceSynthesis
    now = datetime.now(timezone.utc)
    row = EvidenceSynthesis(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        scout_run_id=scout_run_id,
        method_family=method_family,
        synthesis_text=synthesis_text,
        key_findings=json.dumps([]),
        reported_metrics=json.dumps(reported_metrics or []),
        hardware_requirements=json.dumps(hardware or []),
        failure_modes=json.dumps(failure_modes or []),
        open_questions=json.dumps(open_questions or []),
        cited_evidence_ids=json.dumps(cited_evidence_ids or []),
        evidence_count=len(cited_evidence_ids or []),
        paper_count=0,
        model_used="test-model",
        created_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_generate_uses_synthesis_text_and_open_questions(db_session):
    goal = _create_goal(db_session)
    e1 = _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db"])
    e2 = _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_synthesis(
        db_session, goal.id, "beamforming",
        synthesis_text="Beamforming steers acoustic energy into the bright zone.",
        cited_evidence_ids=[e1.id, e2.id],
        reported_metrics=[{"name": "acoustic_contrast_db", "value": "20 dB", "evidence_ids": [e1.id]}],
        open_questions=["How robust is it to head movement?"],
    )

    result = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    card = result.approaches[0]
    assert card.mechanism_summary == "Beamforming steers acoustic energy into the bright zone."
    assert "How robust is it to head movement?" in card.unresolved_questions
    metric = next(m for m in card.reported_metrics if m.metric_name == "acoustic_contrast_db")
    assert metric.value == "20 dB"
    assert metric.source_evidence_id == e1.id


def test_generate_synthesis_evidence_links_grounded(db_session):
    goal = _create_goal(db_session)
    e1 = _seed_evidence(db_session, goal.id, ["beamforming"])
    e2 = _seed_evidence(db_session, goal.id, ["beamforming"])
    # cite a real id plus an invented one that must never appear in links
    _seed_synthesis(
        db_session, goal.id, "beamforming",
        cited_evidence_ids=[e1.id, "invented-id"],
        reported_metrics=[{"name": "contrast", "value": "10", "evidence_ids": [e2.id, "ghost"]}],
    )

    result = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    card = result.approaches[0]
    link_ids = {el.evidence_id for el in card.evidence_links}
    assert "invented-id" not in link_ids
    assert "ghost" not in link_ids
    assert link_ids <= {e1.id, e2.id}
    assert e1.id in link_ids


def test_generate_falls_back_to_algorithmic_without_synthesis(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], text="acoustic contrast control method")
    _seed_evidence(db_session, goal.id, ["beamforming"], text="another chunk")
    # no synthesis seeded -> algorithmic path uses raw chunk text as mechanism_summary

    result = svc.generate_approaches(db_session, goal.id, ApproachGenerateRequest())
    card = result.approaches[0]
    assert card.mechanism_summary in ("acoustic contrast control method", "another chunk")


def test_merge_cross_workspace_rejected(db_session):
    goal1 = _create_goal(db_session)
    goal2 = _create_goal(db_session)
    a1 = svc.create(db_session, goal1.id, ApproachCardCreate(name="A", method_family="bf"))
    a2 = svc.create(db_session, goal2.id, ApproachCardCreate(name="B", method_family="bf"))
    with pytest.raises(Exception) as exc_info:
        svc.merge_approaches(db_session, ApproachMergeRequest(
            source_approach_id=a1.id,
            target_approach_id=a2.id,
        ))
    assert exc_info.value.status_code == 422
