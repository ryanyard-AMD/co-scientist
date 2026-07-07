import json
import time
import uuid
from datetime import datetime, timezone

import anthropic
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.models.approach import ApproachCard
from coscientist.models.device import DeviceConceptCard
from coscientist.models.experiment import ExperimentCard
from coscientist.models.roadmap import ResearchRoadmapItem
from coscientist.models.score import RubricScore
from coscientist.models.validation import ValidationResult
from coscientist.schemas.roadmap import (
    AgentRoadmapItem,
    ApproachEvidenceGap,
    EvidenceGapResponse,
    ResearchRoadmapItemResponse,
    ResearchRoadmapListResponse,
    RoadmapExecutionOutcomeEnum,
    RoadmapLaneEnum,
    RoadmapStatusEnum,
)
from coscientist.services import evaluation as evaluation_svc
from coscientist.services import goal as goal_svc
from coscientist.services import governance as governance_svc

# Approaches in these terminal/negative states aren't worth chasing evidence for.
_NON_PROMISING_STATUS = {"refuted", "superseded"}
# Raw rubric score below this (or a low-confidence flag) marks a dimension as weak.
_WEAK_DIMENSION_THRESHOLD = 0.5

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    RoadmapStatusEnum.open: {RoadmapStatusEnum.completed, RoadmapStatusEnum.superseded},
    RoadmapStatusEnum.completed: set(),
    RoadmapStatusEnum.superseded: set(),
}


def _to_response(item: ResearchRoadmapItem) -> ResearchRoadmapItemResponse:
    return ResearchRoadmapItemResponse(
        id=item.id,
        workspace_id=item.workspace_id,
        title=item.title,
        description=item.description,
        lane=RoadmapLaneEnum(item.lane),
        status=RoadmapStatusEnum(item.status),
        priority_score=item.priority_score,
        priority_rank=item.priority_rank,
        rationale=item.rationale,
        estimated_cost=item.estimated_cost,
        estimated_information_gain=item.estimated_information_gain,
        source_approach_ids=json.loads(item.source_approach_ids) if item.source_approach_ids else [],
        source_experiment_id=item.source_experiment_id,
        source_device_id=item.source_device_id,
        generation_run_id=item.generation_run_id,
        model_used=item.model_used,
        execution_outcome=(
            RoadmapExecutionOutcomeEnum(item.execution_outcome)
            if item.execution_outcome
            else None
        ),
        provisional=item.provisional,
        evidence_adjusted_score=item.evidence_adjusted_score,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _get_or_404(db: Session, item_id: str, goal_id: str) -> ResearchRoadmapItem:
    item = db.get(ResearchRoadmapItem, item_id)
    if item is None or item.workspace_id != goal_id:
        raise HTTPException(status_code=404, detail=f"Roadmap item {item_id!r} not found")
    return item


def _run_roadmap_agent(db: Session, goal_id: str, goal, context: dict) -> list[AgentRoadmapItem]:
    success_criteria = (
        json.loads(goal.success_criteria) if isinstance(goal.success_criteria, str) else []
    )
    device_constraints = (
        json.loads(goal.device_constraints) if isinstance(goal.device_constraints, str) else {}
    )

    system_prompt = (
        "You are a Research Program Manager Agent for personal sound zone (PSZ) research. "
        "Given the full state of a research goal — approaches, experiments, validation results, "
        "and device concept gaps — you recommend the next highest-value research actions. "
        "Respond with ONLY a JSON array of roadmap item objects. No markdown, no explanation.\n\n"
        "Each object must have these exact keys:\n"
        '  "title": string — short actionable title (imperative, ≤ 10 words)\n'
        '  "description": string — 1-3 sentences describing what to do and why\n'
        '  "lane": one of "conservative", "exploratory", "device_prototype"\n'
        '    conservative = low-risk, near-term, validates known approaches\n'
        '    exploratory = higher-risk, higher-upside, tests novel combinations\n'
        '    device_prototype = hardware/integration steps toward a physical device\n'
        '  "priority_score": float 0.0–1.0 (1.0 = highest value; rank by information_gain × device_relevance / cost)\n'
        '  "rationale": string — why this is the next best action given current evidence gaps\n'
        '  "estimated_cost": one of "low", "medium", "high"\n'
        '  "estimated_information_gain": one of "low", "medium", "high"\n'
        '  "source_approach_ids": list of approach IDs this item addresses (can be empty)\n'
        '  "source_experiment_id": experiment ID if this item is a follow-up to a specific experiment, else null\n'
        '  "source_device_id": device concept ID if this item addresses a specific device gap, else null\n\n'
        "Order items by priority_score descending. Include items that:\n"
        "1. Fill evidence gaps for promising approaches with weak evidence\n"
        "2. Follow up on experiments that failed or need robustness testing\n"
        "3. Address unresolved risks in device concepts\n"
        "4. Advance approach maturity from theoretical → simulated → measured\n"
        "Generate between 3 and 15 items."
    )

    user_message = (
        f"## Goal\n"
        f"Name: {goal.name}\n"
        f"Description: {goal.description or ''}\n"
        f"Target application: {goal.target_application}\n\n"
        f"## Success Criteria\n{json.dumps(success_criteria, indent=2)}\n\n"
        f"## Device Constraints\n{json.dumps(device_constraints, indent=2)}\n\n"
        f"## Approaches\n{json.dumps(context['approaches'], indent=2)}\n\n"
        f"## Experiments\n{json.dumps(context['experiments'], indent=2)}\n\n"
        f"## Validation Results\n{json.dumps(context['validation_results'], indent=2)}\n\n"
        f"## Device Concepts\n{json.dumps(context['device_concepts'], indent=2)}\n\n"
        f"## Evidence Gaps (per promising approach)\n{json.dumps(context['evidence_gaps'], indent=2)}\n\n"
        "Recommend the next highest-value research actions. "
        "Prioritize closing the evidence gaps listed above, then follow-up "
        "experiments and device prototype steps."
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    start = time.monotonic()
    message = client.messages.create(
        model=settings.validation_model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    raw = message.content[0].text.strip()
    governance_svc.log_agent_call(
        db=db,
        workspace_id=goal_id,
        service="roadmap",
        action="generate_roadmap",
        model_used=settings.validation_model,
        prompt_tokens=message.usage.input_tokens,
        completion_tokens=message.usage.output_tokens,
        elapsed_ms=elapsed_ms,
        response_summary=raw[:512],
    )
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            data = [data]
        items = [AgentRoadmapItem(**item) for item in data]
        return sorted(items, key=lambda x: x.priority_score, reverse=True)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Roadmap agent returned unparseable response: {exc}",
        )


def _build_context(db: Session, goal_id: str) -> dict:
    approaches = list(
        db.scalars(select(ApproachCard).where(ApproachCard.workspace_id == goal_id))
    )
    approach_ids = [a.id for a in approaches]

    scores = list(
        db.scalars(select(RubricScore).where(RubricScore.approach_id.in_(approach_ids)))
    ) if approach_ids else []

    score_by_approach: dict[str, dict] = {}
    for s in scores:
        if s.approach_id not in score_by_approach:
            score_by_approach[s.approach_id] = {}
        score_by_approach[s.approach_id][s.dimension] = round(s.weighted_score, 3)

    experiments = list(
        db.scalars(select(ExperimentCard).where(ExperimentCard.workspace_id == goal_id))
    )

    validation_results = list(
        db.scalars(
            select(ValidationResult).where(ValidationResult.goal_id == goal_id)
        )
    ) if approach_ids else []

    device_concepts = list(
        db.scalars(
            select(DeviceConceptCard).where(DeviceConceptCard.workspace_id == goal_id)
        )
    )

    return {
        "approaches": [
            {
                "id": a.id,
                "name": a.name,
                "method_family": a.method_family,
                "maturity": a.maturity,
                "status": a.status,
                "hardware_requirements": json.loads(a.hardware_requirements or "[]"),
                "risks_and_limitations": json.loads(a.risks_and_limitations or "[]"),
                "rubric_scores": score_by_approach.get(a.id, {}),
            }
            for a in approaches
        ],
        "experiments": [
            {
                "id": e.id,
                "name": e.name,
                "status": e.status,
                "type": e.experiment_type,
                "estimated_cost": e.estimated_cost,
                "approach_ids": json.loads(e.approach_ids or "[]"),
            }
            for e in experiments
        ],
        "validation_results": [
            {
                "experiment_id": v.experiment_id,
                "approach_id": v.approach_id,
                "decision": v.decision,
                "confidence": v.confidence,
                "refinement_suggestions": json.loads(v.refinement_suggestions or "[]"),
            }
            for v in validation_results
        ],
        "device_concepts": [
            {
                "id": d.id,
                "name": d.name,
                "maturity": d.maturity,
                "unresolved_risks": json.loads(d.unresolved_risks or "[]"),
                "next_steps": json.loads(d.next_steps or "[]"),
                "approach_ids": json.loads(d.approach_ids or "[]"),
            }
            for d in device_concepts
        ],
        "evidence_gaps": [
            g.model_dump() for g in identify_evidence_gaps(db, goal_id).gaps
        ],
    }


def generate(db: Session, goal_id: str) -> ResearchRoadmapListResponse:
    goal_svc.raise_if_restricted(db, goal_id)
    goal = goal_svc.get(db, goal_id)

    context = _build_context(db, goal_id)

    if not context["approaches"]:
        return ResearchRoadmapListResponse(items=[], total=0, generation_run_id=None)

    agent_items = _run_roadmap_agent(db, goal_id, goal, context)

    generation_run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    db_items = []
    for rank, agent_item in enumerate(agent_items, start=1):
        item = ResearchRoadmapItem(
            id=str(uuid.uuid4()),
            workspace_id=goal_id,
            title=agent_item.title,
            description=agent_item.description,
            lane=agent_item.lane.value,
            status="open",
            priority_score=agent_item.priority_score,
            priority_rank=rank,
            rationale=agent_item.rationale,
            estimated_cost=agent_item.estimated_cost,
            estimated_information_gain=agent_item.estimated_information_gain,
            source_approach_ids=json.dumps(agent_item.source_approach_ids),
            source_experiment_id=agent_item.source_experiment_id,
            source_device_id=agent_item.source_device_id,
            generation_run_id=generation_run_id,
            model_used=settings.validation_model,
            created_at=now,
            updated_at=now,
        )
        db.add(item)
        db_items.append(item)

    db.commit()
    for item in db_items:
        db.refresh(item)

    return ResearchRoadmapListResponse(
        items=[_to_response(i) for i in db_items],
        total=len(db_items),
        generation_run_id=generation_run_id,
    )


def get_roadmap(
    db: Session,
    goal_id: str,
    lane: RoadmapLaneEnum | None = None,
    status: RoadmapStatusEnum | None = None,
    skip: int = 0,
    limit: int = 50,
) -> ResearchRoadmapListResponse:
    # Rank by the validation-aware score when execution evidence has adjusted it
    # (CS-ROADMAP-008), falling back to the agent's original priority_score.
    effective_score = func.coalesce(
        ResearchRoadmapItem.evidence_adjusted_score,
        ResearchRoadmapItem.priority_score,
    )
    stmt = (
        select(ResearchRoadmapItem)
        .where(ResearchRoadmapItem.workspace_id == goal_id)
        .order_by(
            effective_score.desc(),
            ResearchRoadmapItem.created_at.desc(),
        )
    )
    if lane is not None:
        stmt = stmt.where(ResearchRoadmapItem.lane == lane.value)
    if status is not None:
        stmt = stmt.where(ResearchRoadmapItem.status == status.value)

    all_items = list(db.scalars(stmt))
    total = len(all_items)
    page = all_items[skip : skip + limit]
    return ResearchRoadmapListResponse(items=[_to_response(i) for i in page], total=total)


def get_item(db: Session, item_id: str, goal_id: str) -> ResearchRoadmapItemResponse:
    item = _get_or_404(db, item_id, goal_id)
    return _to_response(item)


def transition_item(
    db: Session,
    item_id: str,
    goal_id: str,
    new_status: RoadmapStatusEnum,
) -> ResearchRoadmapItemResponse:
    item = _get_or_404(db, item_id, goal_id)
    current = RoadmapStatusEnum(item.status)
    allowed = ALLOWED_TRANSITIONS[current]
    if new_status not in allowed:
        allowed_vals = sorted(s.value for s in allowed)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot transition from {current.value!r} to {new_status.value!r}. "
                f"Allowed: {allowed_vals or 'none (terminal state)'}"
            ),
        )
    item.status = new_status.value
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return _to_response(item)


def identify_evidence_gaps(db: Session, goal_id: str) -> EvidenceGapResponse:
    """Find, per promising approach, which claims lack evidence and which rubric
    dimensions are weak — the structured "what must be tested" view (CS-ROADMAP-003).
    """
    goal_svc.get(db, goal_id)
    approaches = list(
        db.scalars(select(ApproachCard).where(ApproachCard.workspace_id == goal_id))
    )

    scores_by_approach: dict[str, list[RubricScore]] = {}
    if approaches:
        rows = db.scalars(
            select(RubricScore).where(
                RubricScore.approach_id.in_([a.id for a in approaches])
            )
        )
        for s in rows:
            scores_by_approach.setdefault(s.approach_id, []).append(s)

    gaps: list[ApproachEvidenceGap] = []
    for a in approaches:
        if a.status in _NON_PROMISING_STATUS:
            continue

        links = json.loads(a.evidence_links) if a.evidence_links else []
        linked_fields = {link.get("claim_field") for link in links if link.get("claim_field")}
        missing = [
            field
            for field in evaluation_svc._CLAIM_FIELDS
            if evaluation_svc._has_content(a, field) and field not in linked_fields
        ]

        dim_scores = scores_by_approach.get(a.id, [])
        weak = [
            s.dimension
            for s in dim_scores
            if s.low_confidence or s.score < _WEAK_DIMENSION_THRESHOLD
        ]

        if not missing and not weak and dim_scores:
            continue

        gaps.append(
            ApproachEvidenceGap(
                approach_id=a.id,
                approach_name=a.name,
                method_family=a.method_family,
                status=a.status,
                missing_claim_fields=missing,
                weak_dimensions=sorted(set(weak)),
                unscored=not dim_scores,
            )
        )

    return EvidenceGapResponse(goal_id=goal_id, gaps=gaps, total=len(gaps))


def list_for_experiment(
    db: Session, experiment_id: str
) -> list[ResearchRoadmapItemResponse]:
    """Roadmap items that trace back to a specific experiment (CS-UI-013)."""
    items = db.scalars(
        select(ResearchRoadmapItem)
        .where(ResearchRoadmapItem.source_experiment_id == experiment_id)
        .order_by(ResearchRoadmapItem.priority_rank)
    ).all()
    return [_to_response(i) for i in items]


def retire_for_experiment(db: Session, experiment_id: str, goal_id: str) -> None:
    """Mark open roadmap items linked to a completed/failed experiment as completed."""
    items = list(
        db.scalars(
            select(ResearchRoadmapItem).where(
                ResearchRoadmapItem.workspace_id == goal_id,
                ResearchRoadmapItem.source_experiment_id == experiment_id,
                ResearchRoadmapItem.status == RoadmapStatusEnum.open.value,
            )
        )
    )
    if not items:
        return
    now = datetime.now(timezone.utc)
    for item in items:
        item.status = RoadmapStatusEnum.completed.value
        item.updated_at = now
    db.commit()
