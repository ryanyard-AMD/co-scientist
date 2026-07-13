import json

import pytest
from fastapi import HTTPException

from coscientist.clients.retrieval import ChunkResult, QueryResponse
from coscientist.schemas.goal import GoalCreate, SuccessCriterion
from coscientist.schemas.scout import EvidenceStrengthEnum, ScoutRunRequest
from coscientist.services import goal as goal_svc
from coscientist.services import scout as scout_svc
from conftest import MockRetrievalClient, make_artifact, make_chunk

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


def test_agent_output_coerces_dict_string_fields():
    # Lenient models sometimes return list-of-dict where strings are expected.
    out = AgentSynthesisOutput(
        synthesis_text="x",
        key_findings=[
            {"name": "Core SZC", "finding": "minimizes inter-zone interference"},
            "plain string",
        ],
        hardware_requirements=[{"name": "loudspeaker array"}],
        open_questions=[{"text": "robustness?"}],
        failure_modes=["reverberation", {"description": "phase error", "severity": "high"}],
    )
    assert out.key_findings == [
        "Core SZC: minimizes inter-zone interference",
        "plain string",
    ]
    assert out.hardware_requirements == ["loudspeaker array"]
    assert out.open_questions == ["robustness?"]
    assert [(f.description, f.severity) for f in out.failure_modes] == [
        ("reverberation", "medium"),
        ("phase error", "high"),
    ]


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
        failure_modes=[
            {"description": "reverberation degrades contrast", "severity": "high"},
        ],
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


def test_failure_mode_severity_stored_and_surfaced(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    with patch.object(scout_svc, "_run_synthesis_agent", side_effect=_fake_synthesis):
        result = scout_svc.run_scout(
            db_session, goal.id, ScoutRunRequest(synthesize=True), retrieval_client=mock
        )
    # Response surfaces failure modes as plain description strings.
    for s in result.syntheses:
        assert s.failure_modes == ["reverberation degrades contrast"]
    # Raw storage keeps the structured {description, severity} shape.
    from coscientist.models.synthesis import EvidenceSynthesis

    rows = db_session.query(EvidenceSynthesis).all()
    assert rows
    for row in rows:
        stored = json.loads(row.failure_modes)
        assert stored == [
            {"description": "reverberation degrades contrast", "severity": "high"}
        ]


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


# --- Scout quality gate (substantive filter, dedup, score floor, artifacts) ---


def test_header_only_chunk_marked_non_substantive(db_session):
    chunk = make_chunk(
        chunk_id="hdr",
        text="2.3. Controller and Adaptive Filtering Design",
        section_title="Methods",
    )
    mock = MockRetrievalClient(chunks=[chunk])
    goal = _create_goal(db_session)
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    items, _ = scout_svc.get_evidence(db_session, goal.id)
    assert len(items) == 1
    assert items[0].is_substantive is False


def test_reference_section_chunk_marked_non_substantive(db_session):
    chunk = make_chunk(
        chunk_id="ref",
        text="Smith J Jones K acoustic methods overview survey paper",
        section_title="References",
    )
    mock = MockRetrievalClient(chunks=[chunk])
    goal = _create_goal(db_session)
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    items, _ = scout_svc.get_evidence(db_session, goal.id)
    assert len(items) == 1
    assert items[0].is_substantive is False


def test_identical_text_deduplicated(db_session):
    chunks = [
        make_chunk(chunk_id="a", text="Acoustic contrast control maximizes the bright zone energy difference."),
        make_chunk(chunk_id="b", text="Acoustic contrast control maximizes the bright zone energy difference."),
    ]
    mock = MockRetrievalClient(chunks=chunks)
    goal = _create_goal(db_session)
    result = scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    assert result.evidence_count == 1


def test_score_zero_chunk_dropped(db_session):
    chunks = [
        make_chunk(chunk_id="real", score=0.8),
        make_chunk(chunk_id="ghost", paper_id="paper_x", text="Graph expansion neighbor chunk text here.", score=0.0),
    ]
    mock = MockRetrievalClient(chunks=chunks)
    goal = _create_goal(db_session)
    result = scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    items, _ = scout_svc.get_evidence(db_session, goal.id)
    assert all(i.chunk_id != "ghost" for i in items)
    assert result.evidence_count == 1


def test_artifact_ingested_as_evidence(db_session):
    chunk = make_chunk(chunk_id="c1")
    artifact = make_artifact()
    mock = MockRetrievalClient(chunks=[chunk], artifacts=[artifact])
    goal = _create_goal(db_session)
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    items, _ = scout_svc.get_evidence(db_session, goal.id)
    artifact_items = [i for i in items if i.record_kind == "artifact"]
    assert len(artifact_items) == 1
    assert artifact_items[0].is_substantive is True


def test_synthesis_excludes_non_substantive_records(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    chunks = [
        make_chunk(
            chunk_id="good",
            paper_id="paper_good",
            text="Acoustic contrast control optimizes loudspeaker signals to maximize bright zone energy.",
        ),
        make_chunk(
            chunk_id="hdr",
            paper_id="paper_hdr",
            text="2.3. Acoustic Contrast Control Subsection Heading",
            section_title="Methods",
        ),
    ]
    mock = MockRetrievalClient(chunks=chunks)
    goal = _create_goal(db_session)

    captured: dict[str, list[str]] = {}

    def _capturing(db, goal_id, method_family, records):
        captured[method_family] = [r.id for r in records]
        return AgentSynthesisOutput(
            synthesis_text=f"Synthesis of {method_family}.",
            cited_evidence_ids=[r.id for r in records],
        )

    with patch.object(scout_svc, "_run_synthesis_agent", side_effect=_capturing):
        scout_svc.run_scout(
            db_session, goal.id, ScoutRunRequest(synthesize=True), retrieval_client=mock
        )

    items, _ = scout_svc.get_evidence(db_session, goal.id)
    header_id = next(i.id for i in items if i.chunk_id == "hdr")
    for ids in captured.values():
        assert header_id not in ids


def test_substantive_weighted_strength(db_session):
    # Six papers, all backed only by non-substantive numbered headers.
    chunks = [
        make_chunk(
            chunk_id=f"hdr_{i}",
            paper_id=f"paper_{i}",
            text=f"2.{i}. Acoustic Contrast Control Subsection Header",
            section_title="Methods",
        )
        for i in range(6)
    ]
    mock = MockRetrievalClient(chunks=chunks)
    goal = _create_goal(db_session)
    result = scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    acc_groups = [g for g in result.groups.groups if g.group_key == "acoustic_contrast_control"]
    assert acc_groups
    assert acc_groups[0].substantive_paper_count == 0
    assert acc_groups[0].evidence_strength == EvidenceStrengthEnum.none_


# --- Resumable synthesis + fresh-run evidence replacement ---


def test_synthesize_run_resumes_from_committed_evidence(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    # Evidence-only run (synthesis interrupted / never requested).
    run = scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    assert scout_svc.get_syntheses(db_session, goal.id) == []

    with patch.object(scout_svc, "_run_synthesis_agent", side_effect=_fake_synthesis):
        rows = scout_svc.synthesize_run(db_session, goal.id)
    assert len(rows) > 0
    fetched = scout_svc.get_syntheses(db_session, goal.id, scout_run_id=run.scout_run_id)
    assert len(fetched) == len(rows)


def test_synthesize_run_is_idempotent(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    with patch.object(scout_svc, "_run_synthesis_agent", side_effect=_fake_synthesis):
        first = scout_svc.synthesize_run(db_session, goal.id)
        second = scout_svc.synthesize_run(db_session, goal.id)
    # Re-running replaces prior rows rather than duplicating them.
    assert len(second) == len(first)
    assert len(scout_svc.get_syntheses(db_session, goal.id)) == len(first)


def test_synthesize_run_no_evidence_raises(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    with pytest.raises(HTTPException) as exc:
        scout_svc.synthesize_run(db_session, goal.id)
    assert exc.value.status_code == 404


def test_full_rerun_replaces_prior_evidence(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    first = scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    second = scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    # A fresh full run is a snapshot: only the latest run's evidence remains.
    items, total = scout_svc.get_evidence(db_session, goal.id)
    assert total == second.evidence_count
    assert all(i.scout_run_id == second.scout_run_id for i in items)
    assert first.scout_run_id != second.scout_run_id


def test_method_filtered_run_appends(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    _, before = scout_svc.get_evidence(db_session, goal.id)
    scout_svc.run_scout(
        db_session,
        goal.id,
        ScoutRunRequest(method_families=["acoustic_contrast_control"]),
        retrieval_client=mock,
    )
    _, after = scout_svc.get_evidence(db_session, goal.id)
    # A method-filtered run must not wipe the prior full snapshot.
    assert after >= before
