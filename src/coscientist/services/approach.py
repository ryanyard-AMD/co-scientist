import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import anthropic
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.models.approach import ApproachCard
from coscientist.models.critic import ApproachCritique
from coscientist.models.evidence import EvidenceRecord
from coscientist.models.synthesis import EvidenceSynthesis
from coscientist.schemas.approach import (
    AgentRevisionOutput,
    ApproachCardCreate,
    ApproachCardResponse,
    ApproachCardUpdate,
    ApproachGenerateRequest,
    ApproachGenerateResponse,
    ApproachMaturityEnum,
    ApproachMergeRequest,
    ApproachRevisionResponse,
    ApproachReviseRequest,
    ApproachStatusEnum,
    DuplicateWarning,
    EvidenceLink,
    EvidenceTypeEnum,
    ReportedMetric,
    ReviseRunResponse,
    RiskItem,
)
from coscientist.schemas.goal import GoalResponse
from coscientist.services import goal as goal_svc
from coscientist.services import governance as governance_svc

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ApproachStatusEnum.generated:          {ApproachStatusEnum.reviewed, ApproachStatusEnum.refuted, ApproachStatusEnum.superseded},
    ApproachStatusEnum.reviewed:           {ApproachStatusEnum.scored, ApproachStatusEnum.refuted, ApproachStatusEnum.superseded},
    ApproachStatusEnum.scored:             {ApproachStatusEnum.experiment_proposed, ApproachStatusEnum.refuted, ApproachStatusEnum.superseded},
    ApproachStatusEnum.experiment_proposed: {ApproachStatusEnum.submitted, ApproachStatusEnum.tested, ApproachStatusEnum.refuted, ApproachStatusEnum.superseded},
    ApproachStatusEnum.submitted:          {ApproachStatusEnum.tested, ApproachStatusEnum.validated, ApproachStatusEnum.refuted, ApproachStatusEnum.inconclusive, ApproachStatusEnum.superseded},
    ApproachStatusEnum.tested:             {ApproachStatusEnum.validated, ApproachStatusEnum.refuted, ApproachStatusEnum.inconclusive, ApproachStatusEnum.superseded},
    ApproachStatusEnum.inconclusive:       {ApproachStatusEnum.experiment_proposed, ApproachStatusEnum.submitted, ApproachStatusEnum.tested, ApproachStatusEnum.validated, ApproachStatusEnum.refuted, ApproachStatusEnum.superseded},
    ApproachStatusEnum.validated:          {ApproachStatusEnum.superseded},
    ApproachStatusEnum.refuted:            {ApproachStatusEnum.superseded},
    ApproachStatusEnum.superseded:         set(),
}


def _to_response(card: ApproachCard) -> ApproachCardResponse:
    return ApproachCardResponse(
        id=card.id,
        workspace_id=card.workspace_id,
        name=card.name,
        method_family=card.method_family,
        domain=card.domain,
        problem_fit=card.problem_fit,
        mechanism_summary=card.mechanism_summary,
        key_assumptions=json.loads(card.key_assumptions) if card.key_assumptions else [],
        reported_metrics=[ReportedMetric(**m) for m in json.loads(card.reported_metrics)] if card.reported_metrics else [],
        hardware_requirements=json.loads(card.hardware_requirements) if card.hardware_requirements else [],
        device_relevance=card.device_relevance,
        risks_and_limitations=[RiskItem(**r) for r in json.loads(card.risks_and_limitations)] if card.risks_and_limitations else [],
        unresolved_questions=json.loads(card.unresolved_questions) if card.unresolved_questions else [],
        suggested_experiments=json.loads(card.suggested_experiments) if card.suggested_experiments else [],
        evidence_links=[EvidenceLink(**e) for e in json.loads(card.evidence_links)] if card.evidence_links else [],
        status=ApproachStatusEnum(card.status),
        maturity=ApproachMaturityEnum(card.maturity),
        generation_run_id=card.generation_run_id,
        merged_into_id=card.merged_into_id,
        revised_from_id=card.revised_from_id,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _get_or_404(db: Session, approach_id: str) -> ApproachCard:
    card = db.get(ApproachCard, approach_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Approach {approach_id!r} not found")
    return card


def create(db: Session, goal_id: str, data: ApproachCardCreate) -> ApproachCardResponse:
    goal = goal_svc.get(db, goal_id)
    now = datetime.now(timezone.utc)
    card = ApproachCard(
        id=str(uuid.uuid4()),
        workspace_id=goal.workspace_id,
        name=data.name,
        method_family=data.method_family,
        domain=data.domain,
        problem_fit=data.problem_fit,
        mechanism_summary=data.mechanism_summary,
        key_assumptions=json.dumps(data.key_assumptions),
        reported_metrics=json.dumps([m.model_dump() for m in data.reported_metrics]),
        hardware_requirements=json.dumps(data.hardware_requirements),
        device_relevance=data.device_relevance,
        risks_and_limitations=json.dumps([r.model_dump() for r in data.risks_and_limitations]),
        unresolved_questions=json.dumps(data.unresolved_questions),
        suggested_experiments=json.dumps(data.suggested_experiments),
        evidence_links=json.dumps([e.model_dump() for e in data.evidence_links]),
        status=ApproachStatusEnum.generated.value,
        maturity=data.maturity.value,
        generation_run_id=None,
        merged_into_id=None,
        created_at=now,
        updated_at=now,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return _to_response(card)


def get(db: Session, approach_id: str) -> ApproachCardResponse:
    return _to_response(_get_or_404(db, approach_id))


def list_approaches(
    db: Session,
    goal_id: str,
    *,
    status: ApproachStatusEnum | None = None,
    method_family: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[ApproachCardResponse], int]:
    goal_svc.get(db, goal_id)
    q = select(ApproachCard).where(ApproachCard.workspace_id == goal_id)
    if status is not None:
        q = q.where(ApproachCard.status == status.value)
    if method_family is not None:
        q = q.where(ApproachCard.method_family == method_family)

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(ApproachCard.method_family).offset(skip).limit(limit)).all()
    return [_to_response(r) for r in rows], total or 0


def update(db: Session, approach_id: str, data: ApproachCardUpdate) -> ApproachCardResponse:
    card = _get_or_404(db, approach_id)
    if data.name is not None:
        card.name = data.name
    if data.problem_fit is not None:
        card.problem_fit = data.problem_fit
    if data.mechanism_summary is not None:
        card.mechanism_summary = data.mechanism_summary
    if data.key_assumptions is not None:
        card.key_assumptions = json.dumps(data.key_assumptions)
    if data.reported_metrics is not None:
        card.reported_metrics = json.dumps([m.model_dump() for m in data.reported_metrics])
    if data.hardware_requirements is not None:
        card.hardware_requirements = json.dumps(data.hardware_requirements)
    if data.device_relevance is not None:
        card.device_relevance = data.device_relevance
    if data.risks_and_limitations is not None:
        card.risks_and_limitations = json.dumps([r.model_dump() for r in data.risks_and_limitations])
    if data.unresolved_questions is not None:
        card.unresolved_questions = json.dumps(data.unresolved_questions)
    if data.suggested_experiments is not None:
        card.suggested_experiments = json.dumps(data.suggested_experiments)
    if data.evidence_links is not None:
        card.evidence_links = json.dumps([e.model_dump() for e in data.evidence_links])
    if data.maturity is not None:
        card.maturity = data.maturity.value
    card.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(card)
    return _to_response(card)


def transition(db: Session, approach_id: str, new_status: ApproachStatusEnum) -> ApproachCardResponse:
    card = _get_or_404(db, approach_id)
    current = ApproachStatusEnum(card.status)
    if new_status not in ALLOWED_TRANSITIONS[current]:
        allowed = {s.value for s in ALLOWED_TRANSITIONS[current]}
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot transition from {current.value!r} to {new_status.value!r}. "
                f"Allowed: {sorted(allowed) or 'none (terminal state)'}"
            ),
        )
    card.status = new_status.value
    card.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(card)
    return _to_response(card)


def delete(db: Session, approach_id: str) -> None:
    card = _get_or_404(db, approach_id)
    if card.status != ApproachStatusEnum.generated.value:
        raise HTTPException(
            status_code=409,
            detail=f"Only generated approaches can be deleted; approach is {card.status!r}",
        )
    db.delete(card)
    db.commit()


def _derive_maturity(evidence_list: list[EvidenceRecord]) -> str:
    all_text = " ".join(r.chunk_text.lower() for r in evidence_list)
    if "validated" in all_text or "field trial" in all_text:
        return "validated"
    if "measured" in all_text or "experiment" in all_text:
        return "measured"
    if "simulation" in all_text or "simulated" in all_text:
        return "simulated"
    return "theoretical"


def _derive_device_relevance(goal: GoalResponse) -> str | None:
    if not goal.device_constraints:
        return None
    dc = goal.device_constraints
    parts = []
    if dc.form_factor:
        parts.append(f"Form factor: {dc.form_factor}")
    if dc.speaker_count:
        parts.append(f"Speaker count: {dc.speaker_count}")
    return "; ".join(parts) if parts else None


def _synthesize_card(
    method_family: str,
    evidence_list: list[EvidenceRecord],
    goal: GoalResponse,
    generation_run_id: str,
    now: datetime,
) -> ApproachCard:
    card_id = str(uuid.uuid4())
    name = method_family.replace("_", " ").title()

    primary = [e for e in evidence_list if e.is_primary_method]
    best = max(primary or evidence_list, key=lambda e: e.score)
    mechanism_summary = best.chunk_text[:500]

    metrics: list[dict] = []
    evidence_links: list[dict] = []
    seen_metrics: set[str] = set()

    for rec in evidence_list:
        metric_names = json.loads(rec.metric_names) if rec.metric_names else []
        for mn in metric_names:
            if mn not in seen_metrics:
                seen_metrics.add(mn)
                metrics.append({
                    "metric_name": mn,
                    "value": None,
                    "unit": None,
                    "source_evidence_id": rec.id,
                    "confidence": rec.confidence,
                    "evidence_type": "direct",
                })
                evidence_links.append({
                    "evidence_id": rec.id,
                    "evidence_type": "direct",
                    "claim_field": "reported_metrics",
                    "confidence": rec.confidence,
                })

    hw_set: set[str] = set()
    hw_linked: set[str] = set()
    for rec in evidence_list:
        hw = json.loads(rec.hardware_assumptions) if rec.hardware_assumptions else []
        for h in hw:
            hw_set.add(h)
            if rec.id not in hw_linked:
                hw_linked.add(rec.id)
                evidence_links.append({
                    "evidence_id": rec.id,
                    "evidence_type": "direct",
                    "claim_field": "hardware_requirements",
                    "confidence": rec.confidence,
                })

    risks: list[dict] = []
    seen_fm: set[str] = set()
    for rec in evidence_list:
        fms = json.loads(rec.failure_modes) if rec.failure_modes else []
        for fm in fms:
            if fm not in seen_fm:
                seen_fm.add(fm)
                risks.append({
                    "description": fm.replace("_", " ").title(),
                    "failure_mode": fm,
                    "severity": None,
                    "evidence_id": rec.id,
                })
                evidence_links.append({
                    "evidence_id": rec.id,
                    "evidence_type": "direct",
                    "claim_field": "risks_and_limitations",
                    "confidence": rec.confidence,
                })

    assumptions = [f"Requires {h.replace('_', ' ')}" for h in sorted(hw_set)]
    if assumptions:
        evidence_links.append({
            "evidence_id": best.id,
            "evidence_type": "inferred",
            "claim_field": "key_assumptions",
            "confidence": best.confidence,
        })

    maturity = _derive_maturity(evidence_list)

    problem_fit = f"Applies {name} to {goal.target_application.replace('_', ' ')}"
    evidence_links.append({
        "evidence_id": best.id,
        "evidence_type": "inferred",
        "claim_field": "problem_fit",
        "confidence": best.confidence,
    })

    device_relevance = _derive_device_relevance(goal)

    evidence_links.append({
        "evidence_id": best.id,
        "evidence_type": "direct",
        "claim_field": "mechanism_summary",
        "confidence": best.confidence,
    })

    return ApproachCard(
        id=card_id,
        workspace_id=goal.workspace_id,
        name=name,
        method_family=method_family,
        domain=goal.target_application,
        problem_fit=problem_fit,
        mechanism_summary=mechanism_summary,
        key_assumptions=json.dumps(assumptions),
        reported_metrics=json.dumps(metrics),
        hardware_requirements=json.dumps(sorted(hw_set)),
        device_relevance=device_relevance,
        risks_and_limitations=json.dumps(risks),
        unresolved_questions=json.dumps([]),
        suggested_experiments=json.dumps([]),
        evidence_links=json.dumps(evidence_links),
        status="generated",
        maturity=maturity,
        generation_run_id=generation_run_id,
        merged_into_id=None,
        created_at=now,
        updated_at=now,
    )


def _synthesize_card_from_synthesis(
    method_family: str,
    evidence_list: list[EvidenceRecord],
    synthesis: EvidenceSynthesis,
    goal: GoalResponse,
    generation_run_id: str,
    now: datetime,
) -> ApproachCard:
    card_id = str(uuid.uuid4())
    name = method_family.replace("_", " ").title()

    valid_ids = {e.id for e in evidence_list}
    conf_by_id = {e.id: e.confidence for e in evidence_list}
    best = max([e for e in evidence_list if e.is_primary_method] or evidence_list, key=lambda e: e.score)

    cited_raw = json.loads(synthesis.cited_evidence_ids) if synthesis.cited_evidence_ids else []
    cited_ids = [eid for eid in cited_raw if eid in valid_ids]
    fallback_id = cited_ids[0] if cited_ids else best.id

    evidence_links: list[dict] = []

    def _link(field: str, eid: str) -> None:
        evidence_links.append({
            "evidence_id": eid,
            "evidence_type": "direct",
            "claim_field": field,
            "confidence": conf_by_id.get(eid),
        })

    mechanism_summary = synthesis.synthesis_text
    for eid in cited_ids:
        _link("mechanism_summary", eid)

    metrics: list[dict] = []
    syn_metrics = json.loads(synthesis.reported_metrics) if synthesis.reported_metrics else []
    for m in syn_metrics:
        m_ids = [eid for eid in m.get("evidence_ids", []) if eid in valid_ids]
        src_id = m_ids[0] if m_ids else fallback_id
        metrics.append({
            "metric_name": m["name"],
            "value": m.get("value"),
            "unit": None,
            "source_evidence_id": src_id,
            "confidence": conf_by_id.get(src_id),
            "evidence_type": "direct",
        })
        for eid in m_ids:
            _link("reported_metrics", eid)

    hw_set: set[str] = set(json.loads(synthesis.hardware_requirements) if synthesis.hardware_requirements else [])
    for rec in evidence_list:
        hw_set.update(json.loads(rec.hardware_assumptions) if rec.hardware_assumptions else [])
    if hw_set:
        for eid in cited_ids:
            _link("hardware_requirements", eid)

    failure_modes = json.loads(synthesis.failure_modes) if synthesis.failure_modes else []
    risks: list[dict] = []
    for fm in failure_modes:
        risks.append({
            "description": fm,
            "failure_mode": fm,
            "severity": None,
            "evidence_id": fallback_id,
        })
    if risks:
        _link("risks_and_limitations", fallback_id)

    open_questions = json.loads(synthesis.open_questions) if synthesis.open_questions else []

    assumptions = [f"Requires {h.replace('_', ' ')}" for h in sorted(hw_set)]
    if assumptions:
        evidence_links.append({
            "evidence_id": fallback_id,
            "evidence_type": "inferred",
            "claim_field": "key_assumptions",
            "confidence": conf_by_id.get(fallback_id),
        })

    problem_fit = f"Applies {name} to {goal.target_application.replace('_', ' ')}"
    evidence_links.append({
        "evidence_id": fallback_id,
        "evidence_type": "inferred",
        "claim_field": "problem_fit",
        "confidence": conf_by_id.get(fallback_id),
    })

    return ApproachCard(
        id=card_id,
        workspace_id=goal.workspace_id,
        name=name,
        method_family=method_family,
        domain=goal.target_application,
        problem_fit=problem_fit,
        mechanism_summary=mechanism_summary,
        key_assumptions=json.dumps(assumptions),
        reported_metrics=json.dumps(metrics),
        hardware_requirements=json.dumps(sorted(hw_set)),
        device_relevance=_derive_device_relevance(goal),
        risks_and_limitations=json.dumps(risks),
        unresolved_questions=json.dumps(open_questions),
        suggested_experiments=json.dumps([]),
        evidence_links=json.dumps(evidence_links),
        status="generated",
        maturity=_derive_maturity(evidence_list),
        generation_run_id=generation_run_id,
        merged_into_id=None,
        created_at=now,
        updated_at=now,
    )


def generate_approaches(
    db: Session,
    goal_id: str,
    request: ApproachGenerateRequest,
) -> ApproachGenerateResponse:
    goal = goal_svc.get(db, goal_id)

    q = select(EvidenceRecord).where(EvidenceRecord.workspace_id == goal_id)
    if request.scout_run_id:
        q = q.where(EvidenceRecord.scout_run_id == request.scout_run_id)
    records = list(db.scalars(q).all())

    if not records:
        return ApproachGenerateResponse(
            generation_run_id=str(uuid.uuid4()),
            goal_id=goal_id,
            approaches_created=0,
            approaches_skipped_duplicate=0,
            approaches=[],
        )

    method_groups: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for rec in records:
        families = json.loads(rec.method_families) if rec.method_families else []
        for mf in families:
            method_groups[mf].append(rec)

    if request.method_families:
        method_groups = {k: v for k, v in method_groups.items() if k in request.method_families}

    min_count = request.min_evidence_count
    method_groups = {k: v for k, v in method_groups.items() if len(v) >= min_count}

    syn_q = select(EvidenceSynthesis).where(EvidenceSynthesis.workspace_id == goal_id)
    if request.scout_run_id:
        syn_q = syn_q.where(EvidenceSynthesis.scout_run_id == request.scout_run_id)
    # Order so the most recent synthesis per family wins on dict overwrite.
    synthesis_by_family: dict[str, EvidenceSynthesis] = {}
    for syn in db.scalars(syn_q.order_by(EvidenceSynthesis.created_at)).all():
        synthesis_by_family[syn.method_family] = syn

    generation_run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    created: list[ApproachCard] = []
    skipped = 0

    for method_family in sorted(method_groups):
        existing = db.scalar(
            select(ApproachCard).where(
                ApproachCard.workspace_id == goal_id,
                ApproachCard.method_family == method_family,
                ApproachCard.status.notin_(["refuted", "superseded"]),
            )
        )
        if existing:
            skipped += 1
            continue

        synthesis = synthesis_by_family.get(method_family)
        if synthesis is not None:
            card = _synthesize_card_from_synthesis(
                method_family=method_family,
                evidence_list=method_groups[method_family],
                synthesis=synthesis,
                goal=goal,
                generation_run_id=generation_run_id,
                now=now,
            )
        else:
            card = _synthesize_card(
                method_family=method_family,
                evidence_list=method_groups[method_family],
                goal=goal,
                generation_run_id=generation_run_id,
                now=now,
            )
        db.add(card)
        created.append(card)

    db.commit()
    for card in created:
        db.refresh(card)

    return ApproachGenerateResponse(
        generation_run_id=generation_run_id,
        goal_id=goal_id,
        approaches_created=len(created),
        approaches_skipped_duplicate=skipped,
        approaches=[_to_response(c) for c in created],
    )


def find_duplicates(db: Session, goal_id: str) -> list[DuplicateWarning]:
    goal_svc.get(db, goal_id)
    cards = db.scalars(
        select(ApproachCard).where(
            ApproachCard.workspace_id == goal_id,
            ApproachCard.status.notin_(["refuted", "superseded"]),
        )
    ).all()

    by_method: dict[str, list[ApproachCard]] = defaultdict(list)
    for card in cards:
        by_method[card.method_family].append(card)

    warnings: list[DuplicateWarning] = []
    for mf, group in sorted(by_method.items()):
        if len(group) > 1:
            for card in group:
                warnings.append(DuplicateWarning(
                    method_family=mf,
                    existing_approach_id=card.id,
                    existing_status=card.status,
                ))
    return warnings


def merge_approaches(db: Session, data: ApproachMergeRequest) -> ApproachCardResponse:
    source = _get_or_404(db, data.source_approach_id)
    target = _get_or_404(db, data.target_approach_id)

    if source.workspace_id != target.workspace_id:
        raise HTTPException(status_code=422, detail="Cannot merge approaches from different workspaces")

    target_links = json.loads(target.evidence_links) if target.evidence_links else []
    source_links = json.loads(source.evidence_links) if source.evidence_links else []
    seen_ids = {el["evidence_id"] for el in target_links}
    for el in source_links:
        if el["evidence_id"] not in seen_ids:
            target_links.append(el)
            seen_ids.add(el["evidence_id"])
    target.evidence_links = json.dumps(target_links)

    target_metrics = json.loads(target.reported_metrics) if target.reported_metrics else []
    source_metrics = json.loads(source.reported_metrics) if source.reported_metrics else []
    seen_metric_names = {m["metric_name"] for m in target_metrics}
    for m in source_metrics:
        if m["metric_name"] not in seen_metric_names:
            target_metrics.append(m)
            seen_metric_names.add(m["metric_name"])
    target.reported_metrics = json.dumps(target_metrics)

    target_hw = json.loads(target.hardware_requirements) if target.hardware_requirements else []
    source_hw = json.loads(source.hardware_requirements) if source.hardware_requirements else []
    target.hardware_requirements = json.dumps(sorted(set(target_hw) | set(source_hw)))

    target_risks = json.loads(target.risks_and_limitations) if target.risks_and_limitations else []
    source_risks = json.loads(source.risks_and_limitations) if source.risks_and_limitations else []
    seen_fm = {r.get("failure_mode") for r in target_risks if r.get("failure_mode")}
    for r in source_risks:
        if r.get("failure_mode") and r["failure_mode"] not in seen_fm:
            target_risks.append(r)
            seen_fm.add(r["failure_mode"])
    target.risks_and_limitations = json.dumps(target_risks)

    target_assumptions = json.loads(target.key_assumptions) if target.key_assumptions else []
    source_assumptions = json.loads(source.key_assumptions) if source.key_assumptions else []
    target.key_assumptions = json.dumps(list(dict.fromkeys(target_assumptions + source_assumptions)))

    target_uq = json.loads(target.unresolved_questions) if target.unresolved_questions else []
    source_uq = json.loads(source.unresolved_questions) if source.unresolved_questions else []
    target.unresolved_questions = json.dumps(list(dict.fromkeys(target_uq + source_uq)))

    target_se = json.loads(target.suggested_experiments) if target.suggested_experiments else []
    source_se = json.loads(source.suggested_experiments) if source.suggested_experiments else []
    target.suggested_experiments = json.dumps(list(dict.fromkeys(target_se + source_se)))

    target.updated_at = datetime.now(timezone.utc)
    source.status = ApproachStatusEnum.superseded.value
    source.merged_into_id = target.id
    source.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(target)
    return _to_response(target)


_REVISION_TOOL = {
    "name": "record_revision",
    "description": "Record a revised version of one approach card that addresses the critic's issues.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Card name (usually unchanged)."},
            "problem_fit": {"type": "string"},
            "mechanism_summary": {
                "type": "string",
                "description": "How the method works, grounded strictly in cited evidence.",
            },
            "device_relevance": {
                "type": "string",
                "description": (
                    "How the method maps onto the goal's actual target device and its "
                    "acoustic architecture — do NOT inherit generic hardware from source papers."
                ),
            },
            "maturity": {
                "type": "string",
                "enum": ["theoretical", "simulated", "measured", "validated"],
                "description": "Honest maturity: simulation-only results are 'simulated', not 'measured'/'validated'.",
            },
            "key_assumptions": {"type": "array", "items": {"type": "string"}},
            "hardware_requirements": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Hardware the approach needs on the TARGET device, not the source paper's rig.",
            },
            "unresolved_questions": {"type": "array", "items": {"type": "string"}},
            "suggested_experiments": {"type": "array", "items": {"type": "string"}},
            "reported_metrics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "metric_name": {"type": "string"},
                        "value": {"type": "string"},
                        "unit": {"type": "string"},
                        "source_evidence_id": {"type": "string"},
                    },
                    "required": ["metric_name"],
                },
            },
            "risks_and_limitations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "failure_mode": {"type": "string"},
                        "severity": {"type": "string"},
                        "evidence_id": {"type": "string"},
                    },
                    "required": ["description"],
                },
            },
            "cited_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "revision_summary": {
                "type": "string",
                "description": "What changed and why, mapped to the critic's grounding/device-fit/maturity issues.",
            },
        },
        "required": ["name", "maturity", "revision_summary", "cited_evidence_ids"],
    },
}


def _evidence_for_card(db: Session, card: ApproachCardResponse) -> list[EvidenceRecord]:
    evidence_ids = [el.evidence_id for el in card.evidence_links]
    if not evidence_ids:
        return []
    return list(db.scalars(
        select(EvidenceRecord).where(EvidenceRecord.id.in_(evidence_ids))
    ).all())


def _run_revise_agent(
    db: Session,
    goal: GoalResponse,
    card: ApproachCardResponse,
    critique: ApproachCritique,
    evidence: list[EvidenceRecord],
) -> AgentRevisionOutput:
    """Ask Claude to rewrite one approach card to address its critique.

    The model sees the card, the critic's issue lists, and the evidence the card
    cites. It may cite only those evidence_ids; invented ids are stripped by the
    caller before persistence.
    """
    system_prompt = (
        "You are a scientific editor revising ONE approach card to resolve an adversarial "
        "critic's issues. You are given the card, the critic's grounding / device-fit / maturity "
        "issues, and the evidence chunks the card cites. Produce a revised card that: "
        "(1) grounding — every claim, metric, and mechanism detail follows from the cited "
        "evidence; remove or soften anything that overclaims; (2) device fit — rewrite "
        "device_relevance and hardware_requirements for the goal's ACTUAL target device and its "
        "acoustic architecture (judge against the goal description, not the speaker_count field "
        "in isolation: e.g. a parametric-array loudspeaker is a single directional source that "
        "steers via an ultrasonic element array, so speaker_count=1 does not imply zero spatial "
        "degrees of freedom). Do NOT inherit generic hardware (e.g. large loudspeaker arrays) "
        "from the source papers — explain how the method maps onto THIS device's drives/signal "
        "path; (3) maturity — set maturity to match the evidence (simulation-only results are "
        "'simulated', never 'measured' or 'validated'). Record the revision by calling the "
        "record_revision tool. Cite ONLY evidence_id values provided in the chunks; never invent "
        "ids. Preserve the card's method_family scope; keep the name unless it misdescribes the method."
    )

    dc = goal.device_constraints
    device_block = "none"
    if dc:
        device_block = (
            f"form_factor={dc.form_factor or '-'}, speaker_count={dc.speaker_count or '-'}, "
            f"compute_budget={dc.compute_budget or '-'}, "
            f"setup_time_minutes={dc.setup_time_minutes or '-'}"
        )

    goal_block = f"Target application: {goal.target_application}"
    if goal.description:
        goal_block += f"\nDescription: {goal.description}"

    metrics = [f"{m.metric_name}={m.value}" for m in card.reported_metrics]
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

    critique_block = (
        f"Verdict: {critique.verdict}\n"
        f"Summary: {critique.summary}\n"
        f"Grounding issues: {json.loads(critique.grounding_issues) if critique.grounding_issues else []}\n"
        f"Device-fit issues: {json.loads(critique.device_fit_issues) if critique.device_fit_issues else []}\n"
        f"Maturity issues: {json.loads(critique.maturity_issues) if critique.maturity_issues else []}"
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

    user_message = (
        f"## Goal\n{goal_block}\n\n"
        f"## Device constraints\n{device_block}\n\n"
        f"## Approach card (to revise)\n{card_block}\n\n"
        f"## Critic issues to resolve\n{critique_block}\n\n"
        f"## Cited evidence ({len(evidence)})\n"
        + ("\n\n".join(chunk_blocks) if chunk_blocks else "(no linked evidence)")
        + "\n\nRevise the approach card above to resolve every critic issue."
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    start = time.monotonic()
    message = client.messages.create(
        model=settings.validation_model,
        max_tokens=4096,
        system=system_prompt,
        tools=[_REVISION_TOOL],
        tool_choice={"type": "tool", "name": "record_revision"},
        messages=[{"role": "user", "content": user_message}],
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    tool_use = next((b for b in message.content if b.type == "tool_use"), None)
    governance_svc.log_agent_call(
        db=db,
        workspace_id=goal.id,
        service="approach",
        action="revise_approach",
        model_used=settings.validation_model,
        prompt_tokens=message.usage.input_tokens,
        completion_tokens=message.usage.output_tokens,
        elapsed_ms=elapsed_ms,
        response_summary=(json.dumps(tool_use.input)[:512] if tool_use else "no tool_use block"),
    )
    if tool_use is None:
        raise HTTPException(
            status_code=502,
            detail="Revise agent did not return a record_revision tool call",
        )
    try:
        return AgentRevisionOutput(**tool_use.input)
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Revise agent returned invalid output: {exc}",
        )


def _build_revised_card(
    source: ApproachCard,
    output: AgentRevisionOutput,
    valid_ids: set[str],
    conf_by_id: dict[str, float | None],
    revise_run_id: str,
    now: datetime,
) -> ApproachCard:
    """Assemble a new ApproachCard from a revision output, keeping evidence
    grounding: only cited ids that were supplied survive into links/sources."""
    cited = [eid for eid in output.cited_evidence_ids if eid in valid_ids]
    fallback = cited[0] if cited else None

    evidence_links: list[dict] = []

    def _link(field: str, eid: str | None) -> None:
        if eid and eid in valid_ids:
            evidence_links.append({
                "evidence_id": eid,
                "evidence_type": "direct",
                "claim_field": field,
                "confidence": conf_by_id.get(eid),
            })

    metrics: list[dict] = []
    for m in output.reported_metrics:
        src = m.source_evidence_id if m.source_evidence_id in valid_ids else fallback
        metrics.append({
            "metric_name": m.metric_name,
            "value": m.value,
            "unit": m.unit,
            "source_evidence_id": src,
            "confidence": conf_by_id.get(src),
            "evidence_type": "direct",
        })
        _link("reported_metrics", src)

    risks: list[dict] = []
    for r in output.risks_and_limitations:
        eid = r.evidence_id if r.evidence_id in valid_ids else fallback
        risks.append({
            "description": r.description,
            "failure_mode": r.failure_mode,
            "severity": r.severity,
            "evidence_id": eid,
        })
        _link("risks_and_limitations", eid)

    for field in ("mechanism_summary", "problem_fit", "hardware_requirements", "key_assumptions", "device_relevance"):
        for eid in cited:
            _link(field, eid)

    return ApproachCard(
        id=str(uuid.uuid4()),
        workspace_id=source.workspace_id,
        name=output.name or source.name,
        method_family=source.method_family,
        domain=source.domain,
        problem_fit=output.problem_fit,
        mechanism_summary=output.mechanism_summary,
        key_assumptions=json.dumps(output.key_assumptions),
        reported_metrics=json.dumps(metrics),
        hardware_requirements=json.dumps(output.hardware_requirements),
        device_relevance=output.device_relevance,
        risks_and_limitations=json.dumps(risks),
        unresolved_questions=json.dumps(output.unresolved_questions),
        suggested_experiments=json.dumps(output.suggested_experiments),
        evidence_links=json.dumps(evidence_links),
        status=ApproachStatusEnum.generated.value,
        maturity=output.maturity.value,
        generation_run_id=revise_run_id,
        merged_into_id=None,
        revised_from_id=source.id,
        created_at=now,
        updated_at=now,
    )


def _latest_critique(db: Session, approach_id: str) -> ApproachCritique | None:
    return db.scalar(
        select(ApproachCritique)
        .where(ApproachCritique.approach_id == approach_id)
        .order_by(ApproachCritique.created_at.desc())
        .limit(1)
    )


def revise_approaches(
    db: Session,
    goal_id: str,
    request: ApproachReviseRequest,
) -> ReviseRunResponse:
    goal = goal_svc.get(db, goal_id)

    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=422,
            detail="Revise requires an Anthropic API key (set CS_ANTHROPIC_API_KEY).",
        )

    q = select(ApproachCard).where(
        ApproachCard.workspace_id == goal_id,
        ApproachCard.status == ApproachStatusEnum.generated.value,
    )
    if request.method_families:
        q = q.where(ApproachCard.method_family.in_(request.method_families))
    cards = list(db.scalars(q.order_by(ApproachCard.method_family)).all())

    revise_run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    revisions: list[ApproachRevisionResponse] = []
    applied_count = 0

    for card in cards:
        critique = _latest_critique(db, card.id)
        if critique is None or critique.verdict != "revise":
            continue

        card_response = _to_response(card)
        evidence = _evidence_for_card(db, card_response)
        valid_ids = {e.id for e in evidence}
        conf_by_id = {e.id: e.confidence for e in evidence}

        output = _run_revise_agent(db, goal, card_response, critique, evidence)

        new_card = _build_revised_card(
            source=card,
            output=output,
            valid_ids=valid_ids,
            conf_by_id=conf_by_id,
            revise_run_id=revise_run_id,
            now=now,
        )

        applied = False
        revised_card_resp: ApproachCardResponse | None = None
        revised_id: str | None = None
        if request.apply:
            card.status = ApproachStatusEnum.superseded.value
            card.merged_into_id = new_card.id
            card.updated_at = now
            db.add(new_card)
            applied = True
            applied_count += 1
            revised_id = new_card.id
            revised_card_resp = _to_response(new_card)
        else:
            revised_card_resp = _to_response(new_card)

        revisions.append(ApproachRevisionResponse(
            source_approach_id=card.id,
            source_status=card.status,
            method_family=card.method_family,
            revised_approach_id=revised_id,
            revision_summary=output.revision_summary,
            maturity_before=card_response.maturity.value,
            maturity_after=output.maturity.value,
            applied=applied,
            revised_card=revised_card_resp,
        ))

    if request.apply:
        db.commit()

    return ReviseRunResponse(
        revise_run_id=revise_run_id,
        goal_id=goal_id,
        revised_count=len(revisions),
        applied_count=applied_count,
        revisions=revisions,
    )
