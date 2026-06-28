import pytest
from fastapi import HTTPException

from coscientist.clients.retrieval import ChunkResult, QueryResponse
from coscientist.schemas.goal import GoalCreate, SuccessCriterion
from coscientist.schemas.scout import EvidenceStrengthEnum, ScoutRunRequest
from coscientist.services import goal as goal_svc
from coscientist.services import scout as scout_svc
from conftest import MockRetrievalClient, make_chunk

_CRITERIA = [SuccessCriterion(name="acoustic_contrast", operator=">=", target=20.0, unit="dB")]


def _create_goal(db, name="PSZ Test"):
    return goal_svc.create(
        db,
        GoalCreate(
            name=name,
            target_application="personal_sound_zones",
            success_criteria=_CRITERIA,
        ),
    )


def test_run_scout_creates_evidence_records(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    result = scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    assert result.evidence_count == 3
    assert result.summary.total_papers == 2


def test_run_scout_deduplicates_chunks(db_session):
    chunks = [make_chunk(chunk_id="dup_1"), make_chunk(chunk_id="dup_1")]
    mock = MockRetrievalClient(chunks=chunks)
    result = scout_svc.run_scout(db_session, goal_id=_create_goal(db_session).id, request=ScoutRunRequest(), retrieval_client=mock)
    assert result.evidence_count == 1


def test_run_scout_classifies_methods(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    result = scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    items, _ = scout_svc.get_evidence(db_session, goal.id)
    method_sets = [set(i.method_families) for i in items]
    assert any("acoustic_contrast_control" in ms for ms in method_sets)


def test_run_scout_primary_vs_incidental(db_session):
    primary_chunk = make_chunk(
        chunk_id="primary",
        title="Acoustic Contrast Control Methods",
        text="Acoustic contrast control is the main topic of this paper.",
    )
    incidental_chunk = make_chunk(
        chunk_id="incidental",
        title="General Audio Processing",
        text="Other techniques exist. " * 50 + "acoustic contrast control was briefly mentioned.",
    )
    mock = MockRetrievalClient(chunks=[primary_chunk, incidental_chunk])
    goal = _create_goal(db_session)
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    items, _ = scout_svc.get_evidence(db_session, goal.id)
    primary_items = [i for i in items if i.is_primary_method]
    incidental_items = [i for i in items if not i.is_primary_method]
    assert len(primary_items) >= 1
    assert len(incidental_items) >= 1


def test_run_scout_evidence_strength(db_session):
    chunks = [
        make_chunk(chunk_id=f"c_{i}", paper_id=f"paper_{i}", score=0.9 - i * 0.01)
        for i in range(6)
    ]
    mock = MockRetrievalClient(chunks=chunks)
    goal = _create_goal(db_session)
    result = scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    groups = result.groups
    acc_groups = [g for g in groups.groups if g.group_key == "acoustic_contrast_control"]
    if acc_groups:
        assert acc_groups[0].evidence_strength == EvidenceStrengthEnum.strong


def test_run_scout_sparsity_warnings(db_session):
    chunks = [make_chunk(
        chunk_id="lonely",
        text="This paper discusses beamforming techniques only.",
    )]
    mock = MockRetrievalClient(chunks=chunks)
    goal = _create_goal(db_session)
    result = scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    warned_categories = [w.query_or_category for w in result.summary.warnings]
    assert "pressure_matching" in warned_categories


def test_run_scout_goal_not_found(db_session):
    mock = MockRetrievalClient()
    with pytest.raises(HTTPException) as exc:
        scout_svc.run_scout(db_session, "nonexistent", ScoutRunRequest(), retrieval_client=mock)
    assert exc.value.status_code == 404


def test_run_scout_method_filter(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    request = ScoutRunRequest(method_families=["pressure_matching"])
    result = scout_svc.run_scout(db_session, goal.id, request, retrieval_client=mock)
    items, _ = scout_svc.get_evidence(db_session, goal.id)
    for item in items:
        has_pm = "pressure_matching" in item.method_families
        has_pm_text = "pressure matching" in item.chunk_text.lower()
        assert has_pm or has_pm_text


def test_get_evidence_returns_persisted(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    items, total = scout_svc.get_evidence(db_session, goal.id)
    assert total == 3
    assert len(items) == 3


def test_get_evidence_by_id(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    items, _ = scout_svc.get_evidence(db_session, goal.id)
    detail = scout_svc.get_evidence_by_id(db_session, goal.id, items[0].id)
    assert detail.id == items[0].id


def test_get_evidence_by_id_not_found(db_session):
    goal = _create_goal(db_session)
    with pytest.raises(HTTPException) as exc:
        scout_svc.get_evidence_by_id(db_session, goal.id, "nonexistent")
    assert exc.value.status_code == 404


def test_get_evidence_groups_by_method(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    groups = scout_svc.get_evidence_groups(db_session, goal.id, group_by="method_family")
    assert groups.total_groups > 0
    assert all(g.group_type == "method_family" for g in groups.groups)


def test_get_summary_includes_warnings(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient(chunks=[make_chunk()])
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    summary = scout_svc.get_summary(db_session, goal.id)
    assert summary.total_evidence >= 1
    assert len(summary.warnings) > 0


def test_get_summary_empty(db_session):
    goal = _create_goal(db_session)
    summary = scout_svc.get_summary(db_session, goal.id)
    assert summary.total_evidence == 0


# --- Claude synthesis at scout stage ---

from unittest.mock import patch

from coscientist.config import settings
from coscientist.schemas.scout import AgentSynthesisOutput, ReportedMetric


def _fake_synthesis(db, goal_id, method_family, records):
    # cite the first real record plus one invented id (must be stripped)
    return AgentSynthesisOutput(
        synthesis_text=f"Synthesis of {method_family}.",
        key_findings=["finding one"],
        reported_metrics=[
            ReportedMetric(
                name="acoustic_contrast",
                value="20 dB",
                evidence_ids=[records[0].id, "invented-metric-id"],
            )
        ],
        hardware_requirements=["loudspeaker array"],
        failure_modes=["reverberation"],
        open_questions=["robustness?"],
        cited_evidence_ids=[records[0].id, "invented-id"],
    )


def test_synthesize_persists_rows(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    with patch.object(scout_svc, "_run_synthesis_agent", side_effect=_fake_synthesis):
        result = scout_svc.run_scout(
            db_session, goal.id, ScoutRunRequest(synthesize=True), retrieval_client=mock
        )
    assert len(result.syntheses) > 0
    fetched = scout_svc.get_syntheses(db_session, goal.id)
    assert len(fetched) == len(result.syntheses)
    assert all(s.synthesis_text.startswith("Synthesis of") for s in fetched)


def test_synthesis_strips_invented_citations(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    with patch.object(scout_svc, "_run_synthesis_agent", side_effect=_fake_synthesis):
        result = scout_svc.run_scout(
            db_session, goal.id, ScoutRunRequest(synthesize=True), retrieval_client=mock
        )
    for s in result.syntheses:
        assert "invented-id" not in s.cited_evidence_ids
        for m in s.reported_metrics:
            assert "invented-metric-id" not in m.evidence_ids


def test_synthesize_false_is_noop(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    with patch.object(scout_svc, "_run_synthesis_agent", side_effect=_fake_synthesis) as agent:
        result = scout_svc.run_scout(
            db_session, goal.id, ScoutRunRequest(synthesize=False), retrieval_client=mock
        )
    assert result.syntheses == []
    assert agent.call_count == 0
    assert scout_svc.get_syntheses(db_session, goal.id) == []


def test_synthesize_without_api_key_skips(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    with patch.object(scout_svc, "_run_synthesis_agent", side_effect=_fake_synthesis) as agent:
        result = scout_svc.run_scout(
            db_session, goal.id, ScoutRunRequest(synthesize=True), retrieval_client=mock
        )
    assert result.syntheses == []
    assert agent.call_count == 0
