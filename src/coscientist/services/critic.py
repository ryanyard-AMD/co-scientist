import json
import time
import uuid
from datetime import datetime, timezone

import anthropic
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.models.approach import ApproachCard
from coscientist.models.critic import ApproachCritique
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.approach import ApproachCardResponse, ApproachStatusEnum
from coscientist.schemas.critic import (
    AgentCritiqueOutput,
    ApproachCritiqueRequest,
    ApproachCritiqueResponse,
    CriticVerdictEnum,
    CritiqueRunResponse,
)
from coscientist.schemas.goal import GoalResponse
from coscientist.services import approach as approach_svc
from coscientist.services import goal as goal_svc
from coscientist.services import governance as governance_svc


_CRITIQUE_TOOL = {
    "name": "record_critique",
    "description": "Record an adversarial review of one approach card.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["advance", "revise", "refute"],
                "description": (
                    "advance = sound, ready to score; revise = fixable issues, keep but rework; "
                    "refute = unsound or device-mismatched, should not proceed."
                ),
            },
            "summary": {
                "type": "string",
                "description": "Overall critique grounded in the card and supplied evidence.",
            },
            "grounding_issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Claims in the card that overclaim or are unsupported by cited evidence.",
            },
            "device_fit_issues": {"type": "array", "items": {"type": "string"}},
            "maturity_issues": {"type": "array", "items": {"type": "string"}},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "cited_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": ["verdict", "summary", "cited_evidence_ids"],
    },
}


_VERDICT_TO_STATUS: dict[CriticVerdictEnum, ApproachStatusEnum] = {
    CriticVerdictEnum.advance: ApproachStatusEnum.reviewed,
    CriticVerdictEnum.revise: ApproachStatusEnum.generated,
    CriticVerdictEnum.refute: ApproachStatusEnum.refuted,
}


def _critique_to_response(
    row: ApproachCritique, approach_name: str, method_family: str
) -> ApproachCritiqueResponse:
    return ApproachCritiqueResponse(
        id=row.id,
        workspace_id=row.workspace_id,
        approach_id=row.approach_id,
        approach_name=approach_name,
        method_family=method_family,
        critique_run_id=row.critique_run_id,
        verdict=CriticVerdictEnum(row.verdict),
        summary=row.summary,
        grounding_issues=json.loads(row.grounding_issues) if row.grounding_issues else [],
        device_fit_issues=json.loads(row.device_fit_issues) if row.device_fit_issues else [],
        maturity_issues=json.loads(row.maturity_issues) if row.maturity_issues else [],
        strengths=json.loads(row.strengths) if row.strengths else [],
        cited_evidence_ids=json.loads(row.cited_evidence_ids),
        recommended_status=row.recommended_status,
        applied=row.applied,
        confidence=row.confidence,
        model_used=row.model_used,
        created_at=row.created_at,
    )


def _evidence_for_card(db: Session, card: ApproachCardResponse) -> list[EvidenceRecord]:
    evidence_ids = [el.evidence_id for el in card.evidence_links]
    if not evidence_ids:
        return []
    return list(db.scalars(
        select(EvidenceRecord).where(EvidenceRecord.id.in_(evidence_ids))
    ).all())


def _run_critic_agent(
    db: Session,
    goal: GoalResponse,
    card: ApproachCardResponse,
    evidence: list[EvidenceRecord],
) -> AgentCritiqueOutput:
    """Ask Claude to adversarially review one approach card.

    The model sees the card plus the evidence it cites, and may cite only those
    evidence_ids. Invented ids are stripped by the caller before persistence.
    """
    system_prompt = (
        "You are an adversarial scientific critic. You are given ONE approach card and the "
        "evidence chunks it cites. Judge it on three axes: (1) grounding fidelity — do the "
        "card's mechanism, metrics, and claims actually follow from the cited evidence, or "
        "does it overclaim; (2) device fit — is it viable for the described device and its "
        "acoustic architecture (judge against the goal description, not the speaker_count "
        "field in isolation: e.g. a parametric-array loudspeaker is a single directional "
        "source that steers via an ultrasonic element array, so speaker_count=1 does not "
        "imply zero spatial degrees of freedom); (3) maturity honesty — does the claimed "
        "maturity match the evidence. Record your "
        "review by calling the record_critique tool. Cite ONLY evidence_id values provided in "
        "the chunks; never invent ids. Choose verdict 'advance' (sound), 'revise' (fixable "
        "issues), or 'refute' (unsound or device-mismatched)."
    )

    dc = goal.device_constraints
    device_block = "none"
    if dc:
        device_block = (
            f"form_factor={dc.form_factor or '-'}, speaker_count={dc.speaker_count or '-'}, "
            f"compute_budget={dc.compute_budget or '-'}, "
            f"setup_time_minutes={dc.setup_time_minutes or '-'}"
        )

    metrics = [
        f"{m.metric_name}={m.value}" for m in card.reported_metrics
    ]
    risks = [r.failure_mode or r.description for r in card.risks_and_limitations]

    card_block = (
        f"Name: {card.name}\n"
        f"Method family: {card.method_family}\n"
        f"Claimed maturity: {card.maturity.value}\n"
        f"Problem fit: {card.problem_fit}\n"
        f"Device relevance (claimed): {card.device_relevance or '-'}\n"
        f"Mechanism summary:\n{card.mechanism_summary}\n"
        f"Reported metrics: {metrics or 'none'}\n"
        f"Hardware requirements: {card.hardware_requirements or 'none'}\n"
        f"Risks/limitations: {risks or 'none'}\n"
        f"Unresolved questions: {card.unresolved_questions or 'none'}"
    )

    chunk_blocks = []
    for rec in evidence:
        chunk_blocks.append(
            f"### evidence_id: {rec.id}\n"
            f"Title: {rec.title}"
            + (f" ({rec.year})" if rec.year else "")
            + "\n"
            + (f"Section: {rec.section_title}\n" if rec.section_title else "")
            + f"Text: {rec.chunk_text[:1500]}"
        )

    goal_block = f"Target application: {goal.target_application}"
    if goal.description:
        goal_block += f"\nDescription: {goal.description}"

    user_message = (
        f"## Goal\n{goal_block}\n\n"
        f"## Device constraints\n{device_block}\n\n"
        f"## Approach card\n{card_block}\n\n"
        f"## Cited evidence ({len(evidence)})\n"
        + ("\n\n".join(chunk_blocks) if chunk_blocks else "(no linked evidence)")
        + "\n\nCritique the approach card above."
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    start = time.monotonic()
    message = client.messages.create(
        model=settings.validation_model,
        max_tokens=4096,
        system=system_prompt,
        tools=[_CRITIQUE_TOOL],
        tool_choice={"type": "tool", "name": "record_critique"},
        messages=[{"role": "user", "content": user_message}],
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    tool_use = next((b for b in message.content if b.type == "tool_use"), None)
    governance_svc.log_agent_call(
        db=db,
        workspace_id=goal.id,
        service="critic",
        action="critique_approach",
        model_used=settings.validation_model,
        prompt_tokens=message.usage.input_tokens,
        completion_tokens=message.usage.output_tokens,
        elapsed_ms=elapsed_ms,
        response_summary=(json.dumps(tool_use.input)[:512] if tool_use else "no tool_use block"),
    )
    if tool_use is None:
        raise HTTPException(
            status_code=502,
            detail="Critic agent did not return a record_critique tool call",
        )
    try:
        return AgentCritiqueOutput(**tool_use.input)
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Critic agent returned invalid output: {exc}",
        )


def critique_approaches(
    db: Session,
    goal_id: str,
    request: ApproachCritiqueRequest,
) -> CritiqueRunResponse:
    goal = goal_svc.get(db, goal_id)

    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=422,
            detail="Critic requires an Anthropic API key (set CS_ANTHROPIC_API_KEY).",
        )

    q = select(ApproachCard).where(
        ApproachCard.workspace_id == goal_id,
        ApproachCard.status == ApproachStatusEnum.generated.value,
    )
    if request.method_families:
        q = q.where(ApproachCard.method_family.in_(request.method_families))
    cards = list(db.scalars(q.order_by(ApproachCard.method_family)).all())

    critique_run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    responses: list[ApproachCritiqueResponse] = []
    counts = {CriticVerdictEnum.advance: 0, CriticVerdictEnum.revise: 0, CriticVerdictEnum.refute: 0}
    applied_count = 0

    for card in cards:
        card_response = approach_svc.get(db, card.id)
        evidence = _evidence_for_card(db, card_response)
        valid_ids = {e.id for e in evidence}

        output = _run_critic_agent(db, goal, card_response, evidence)
        cited = [eid for eid in output.cited_evidence_ids if eid in valid_ids]

        recommended_status = _VERDICT_TO_STATUS[output.verdict]
        applied = False
        if request.apply and output.verdict in (CriticVerdictEnum.advance, CriticVerdictEnum.refute):
            approach_svc.transition(db, card.id, recommended_status)
            applied = True
            applied_count += 1

        row = ApproachCritique(
            id=str(uuid.uuid4()),
            workspace_id=goal_id,
            approach_id=card.id,
            critique_run_id=critique_run_id,
            verdict=output.verdict.value,
            summary=output.summary,
            grounding_issues=json.dumps(output.grounding_issues),
            device_fit_issues=json.dumps(output.device_fit_issues),
            maturity_issues=json.dumps(output.maturity_issues),
            strengths=json.dumps(output.strengths),
            cited_evidence_ids=json.dumps(cited),
            recommended_status=recommended_status.value,
            applied=applied,
            confidence=output.confidence,
            model_used=settings.validation_model,
            created_at=now,
        )
        db.add(row)
        counts[output.verdict] += 1
        responses.append(_critique_to_response(row, card.name, card.method_family))

    db.commit()

    return CritiqueRunResponse(
        critique_run_id=critique_run_id,
        goal_id=goal_id,
        critiqued_count=len(cards),
        advance_count=counts[CriticVerdictEnum.advance],
        revise_count=counts[CriticVerdictEnum.revise],
        refute_count=counts[CriticVerdictEnum.refute],
        applied_count=applied_count,
        critiques=responses,
    )


def get_critiques(
    db: Session,
    goal_id: str,
    *,
    approach_id: str | None = None,
    critique_run_id: str | None = None,
) -> list[ApproachCritiqueResponse]:
    goal_svc.get(db, goal_id)
    q = select(ApproachCritique).where(ApproachCritique.workspace_id == goal_id)
    if approach_id:
        q = q.where(ApproachCritique.approach_id == approach_id)
    if critique_run_id:
        q = q.where(ApproachCritique.critique_run_id == critique_run_id)
    rows = list(db.scalars(q.order_by(ApproachCritique.created_at.desc())).all())

    name_by_id: dict[str, tuple[str, str]] = {}
    for row in rows:
        if row.approach_id not in name_by_id:
            card = db.get(ApproachCard, row.approach_id)
            name_by_id[row.approach_id] = (
                (card.name, card.method_family) if card else ("(deleted)", "-")
            )
    return [
        _critique_to_response(row, *name_by_id[row.approach_id]) for row in rows
    ]
