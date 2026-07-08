"""Phase 1: claims ingested as query-time evidence and surfaced to synthesis."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from coscientist.clients.retrieval import ClaimRelationship, ClaimResult
from coscientist.config import settings
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.goal import GoalCreate, SuccessCriterion
from coscientist.schemas.scout import ScoutRunRequest
from coscientist.services import goal as goal_svc
from coscientist.services import scout as scout_svc
from conftest import MockRetrievalClient

_CRITERIA = [SuccessCriterion(name="acoustic_contrast", operator=">=", target=20.0, unit="dB")]


def _create_goal(db, name="PSZ Claims Test"):
    return goal_svc.create(
        db,
        GoalCreate(
            name=name,
            target_application="personal_sound_zones",
            success_criteria=_CRITERIA,
        ),
    )


_FINDING = ClaimResult(
    claim_id="claim_finding",
    text="Acoustic contrast control achieves 20 dB contrast in the bright zone.",
    claim_type="finding",
    paper_id="paper_1",
    title="ACC for Personal Sound Zones",
    chunk_ids=["chunk_a"],
    confidence=0.9,
    score=0.7,
)
_LIMITATION = ClaimResult(
    claim_id="claim_limit",
    text="Acoustic contrast control degrades listening quality compared to pressure matching.",
    claim_type="limitation",
    paper_id="paper_2",
    title="Tradeoffs in Sound Zone Control",
    chunk_ids=["chunk_b"],
    confidence=0.8,
    score=0.6,
    relationships=[
        ClaimRelationship(
            relation="CONTRADICTS",
            target_claim_id="claim_finding",
            rationale="Quality cost not reflected in the contrast-only finding.",
        )
    ],
)


def test_claims_ingested_as_evidence_records(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient(claims=[_FINDING, _LIMITATION])
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)

    claim_recs = (
        db_session.query(EvidenceRecord)
        .filter(EvidenceRecord.record_kind == "claim")
        .all()
    )
    by_source = {r.source_claim_id: r for r in claim_recs}
    # Deduped across every family query by claim_id.
    assert set(by_source) == {"claim_finding", "claim_limit"}

    finding = by_source["claim_finding"]
    assert finding.claim_type == "finding"
    assert finding.confidence == 0.9
    assert finding.chunk_id == "chunk_a"
    assert finding.chunk_text.startswith("Acoustic contrast control achieves")

    limit = by_source["claim_limit"]
    edges = json.loads(limit.claim_relationships)
    assert edges[0]["relation"] == "CONTRADICTS"
    assert edges[0]["target_claim_id"] == "claim_finding"


def test_claims_grouped_into_method_family(db_session):
    goal = _create_goal(db_session)
    mock = MockRetrievalClient(claims=[_FINDING, _LIMITATION])
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    groups = scout_svc.get_evidence_groups(db_session, goal.id, group_by="method_family")
    acc = [g for g in groups.groups if g.group_key == "acoustic_contrast_control"]
    assert acc, "claims should land in the acoustic_contrast_control family"


def test_claims_disabled_ingests_nothing(db_session, monkeypatch):
    monkeypatch.setattr(settings, "scout_use_claims", False)
    goal = _create_goal(db_session)
    mock = MockRetrievalClient(claims=[_FINDING, _LIMITATION])
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=mock)
    claim_recs = (
        db_session.query(EvidenceRecord)
        .filter(EvidenceRecord.record_kind == "claim")
        .count()
    )
    assert claim_recs == 0


def _fake_anthropic_capture(captured):
    """Return a fake anthropic.Anthropic whose messages.create records the prompt."""
    tool_use = SimpleNamespace(type="tool_use", input={
        "synthesis_text": "ok",
        "cited_evidence_ids": [],
        "key_findings": [],
        "reported_metrics": [],
        "hardware_requirements": [],
        "failure_modes": [],
        "open_questions": [],
    })
    message = SimpleNamespace(
        content=[tool_use],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return message

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    return _Client


def test_synthesis_prompt_includes_claims_block(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)

    chunk_rec = EvidenceRecord(
        id="rec_chunk", workspace_id=goal.workspace_id, scout_run_id="run",
        query_text="q", paper_id="paper_1", title="ACC paper", chunk_id="chunk_a",
        chunk_index=0, chunk_text="Chunk about acoustic contrast control.", score=0.7,
        record_kind="chunk",
    )
    finding_rec = EvidenceRecord(
        id="rec_finding", workspace_id=goal.workspace_id, scout_run_id="run",
        query_text="q", paper_id="paper_1", title="ACC paper", chunk_id="chunk_a",
        chunk_index=0, chunk_text=_FINDING.text, score=0.7, record_kind="claim",
        claim_type="finding", confidence=0.9, source_claim_id="claim_finding",
        claim_relationships=json.dumps([]),
    )
    limit_rec = EvidenceRecord(
        id="rec_limit", workspace_id=goal.workspace_id, scout_run_id="run",
        query_text="q", paper_id="paper_2", title="Tradeoffs paper", chunk_id="chunk_b",
        chunk_index=0, chunk_text=_LIMITATION.text, score=0.6, record_kind="claim",
        claim_type="limitation", confidence=0.8, source_claim_id="claim_limit",
        claim_relationships=json.dumps([e.model_dump() for e in _LIMITATION.relationships]),
    )

    captured: dict = {}
    with patch.object(scout_svc.anthropic, "Anthropic", _fake_anthropic_capture(captured)):
        scout_svc._run_synthesis_agent(
            db_session, goal.id, "acoustic_contrast_control",
            [chunk_rec, finding_rec, limit_rec],
        )

    user_msg = captured["messages"][0]["content"]
    assert "Extracted claims (grounded findings)" in user_msg
    assert "[claim:finding" in user_msg
    assert "[claim:limitation" in user_msg
    # CONTRADICTS edge resolved to the target claim's text within the group.
    assert "CONTRADICTS" in user_msg
    assert "20 dB contrast" in user_msg
