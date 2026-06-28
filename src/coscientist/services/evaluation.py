import json

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.models.approach import ApproachCard
from coscientist.models.experiment import ExperimentCard
from coscientist.schemas.evaluation import (
    ApproachUsefulnessMetrics,
    EvaluationReport,
    EvidenceGroundingMetrics,
    ExperimentQualityMetrics,
    UnsupportedClaim,
)
from coscientist.services import experiment as experiment_svc
from coscientist.services import goal as goal_svc

# PRD §20 Success Metrics targets.
USEFULNESS_TARGET = 0.75
TRACEABILITY_TARGET = 1.0
GROUNDING_TARGET = 0.90
UNSUPPORTED_TARGET = 0.05
ACCEPTANCE_TARGET = 0.70
VALIDITY_TARGET = 0.85

# Approach lifecycle status buckets.
_APPROACH_USEFUL = {"reviewed", "scored", "experiment_proposed", "tested", "validated"}
_APPROACH_DISCARDED = {"superseded", "refuted"}

# Experiment lifecycle status buckets.
_EXPERIMENT_ACCEPTED = {"reviewed", "approved", "running", "completed"}
_EXPERIMENT_DISCARDED = {"superseded"}

# Approach fields that carry a research claim and should be grounded in evidence.
# device_relevance is intentionally excluded: it restates the goal's device
# constraints rather than a claim drawn from the literature, so it needs no
# evidence link.
_CLAIM_FIELDS = (
    "mechanism_summary",
    "problem_fit",
    "key_assumptions",
    "reported_metrics",
    "hardware_requirements",
    "risks_and_limitations",
)


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _meets_min(rate: float, target: float, denominator: int) -> bool:
    # No data yet is not a failing gate.
    return denominator == 0 or rate >= target


def _meets_max(rate: float, target: float, denominator: int) -> bool:
    return denominator == 0 or rate <= target


def _has_content(card: ApproachCard, field: str) -> bool:
    raw = getattr(card, field)
    if raw is None:
        return False
    if isinstance(raw, str) and raw.strip().startswith(("[", "{")):
        try:
            return bool(json.loads(raw))
        except json.JSONDecodeError:
            return bool(raw.strip())
    return bool(str(raw).strip())


def approach_usefulness(db: Session, goal_id: str) -> ApproachUsefulnessMetrics:
    goal_svc.get(db, goal_id)
    cards = db.scalars(
        select(ApproachCard).where(ApproachCard.workspace_id == goal_id)
    ).all()

    by_status: dict[str, int] = {}
    useful = discarded = pending = traceable = 0
    for card in cards:
        by_status[card.status] = by_status.get(card.status, 0) + 1
        if card.status in _APPROACH_USEFUL:
            useful += 1
        elif card.status in _APPROACH_DISCARDED:
            discarded += 1
        else:
            pending += 1
        links = json.loads(card.evidence_links) if card.evidence_links else []
        if links:
            traceable += 1

    total = len(cards)
    usefulness_rate = _rate(useful, useful + discarded)
    traceability_rate = _rate(traceable, total)
    return ApproachUsefulnessMetrics(
        goal_id=goal_id,
        total=total,
        by_status=by_status,
        useful_count=useful,
        discarded_count=discarded,
        pending_count=pending,
        usefulness_rate=usefulness_rate,
        usefulness_target=USEFULNESS_TARGET,
        usefulness_meets_target=_meets_min(usefulness_rate, USEFULNESS_TARGET, useful + discarded),
        traceable_count=traceable,
        traceability_rate=traceability_rate,
        traceability_target=TRACEABILITY_TARGET,
        traceability_meets_target=_meets_min(traceability_rate, TRACEABILITY_TARGET, total),
    )


def evidence_grounding(db: Session, goal_id: str) -> EvidenceGroundingMetrics:
    goal_svc.get(db, goal_id)
    cards = db.scalars(
        select(ApproachCard).where(ApproachCard.workspace_id == goal_id)
    ).all()

    grounded = inferred = unsupported = 0
    unsupported_claims: list[UnsupportedClaim] = []
    for card in cards:
        links = json.loads(card.evidence_links) if card.evidence_links else []
        types_by_field: dict[str, set[str]] = {}
        for link in links:
            field = link.get("claim_field")
            if field:
                types_by_field.setdefault(field, set()).add(link.get("evidence_type"))
        for field in _CLAIM_FIELDS:
            if not _has_content(card, field):
                continue
            types = types_by_field.get(field, set())
            if "direct" in types:
                grounded += 1
            elif "inferred" in types:
                inferred += 1
            else:
                unsupported += 1
                unsupported_claims.append(
                    UnsupportedClaim(
                        approach_id=card.id,
                        approach_name=card.name,
                        claim_field=field,
                    )
                )

    total_claims = grounded + inferred + unsupported
    grounding_rate = _rate(grounded + inferred, total_claims)
    unsupported_rate = _rate(unsupported, total_claims)
    return EvidenceGroundingMetrics(
        goal_id=goal_id,
        total_claims=total_claims,
        grounded=grounded,
        inferred=inferred,
        unsupported=unsupported,
        grounding_rate=grounding_rate,
        grounding_target=GROUNDING_TARGET,
        grounding_meets_target=_meets_min(grounding_rate, GROUNDING_TARGET, total_claims),
        unsupported_rate=unsupported_rate,
        unsupported_target=UNSUPPORTED_TARGET,
        unsupported_meets_target=_meets_max(unsupported_rate, UNSUPPORTED_TARGET, total_claims),
        unsupported_claims=unsupported_claims,
    )


def experiment_quality(db: Session, goal_id: str) -> ExperimentQualityMetrics:
    goal_svc.get(db, goal_id)
    cards = db.scalars(
        select(ExperimentCard).where(ExperimentCard.workspace_id == goal_id)
    ).all()

    by_status: dict[str, int] = {}
    accepted = discarded = failed = pending = valid = 0
    invalid_ids: list[str] = []
    for card in cards:
        by_status[card.status] = by_status.get(card.status, 0) + 1
        if card.status in _EXPERIMENT_ACCEPTED:
            accepted += 1
        elif card.status in _EXPERIMENT_DISCARDED:
            discarded += 1
        elif card.status == "failed":
            failed += 1
        else:
            pending += 1
        try:
            experiment_svc.get(db, card.id)
            valid += 1
        except (ValidationError, ValueError):
            invalid_ids.append(card.id)

    total = len(cards)
    acceptance_rate = _rate(accepted, accepted + discarded)
    validity_rate = _rate(valid, total)
    return ExperimentQualityMetrics(
        goal_id=goal_id,
        total=total,
        by_status=by_status,
        accepted_count=accepted,
        discarded_count=discarded,
        failed_count=failed,
        pending_count=pending,
        acceptance_rate=acceptance_rate,
        acceptance_target=ACCEPTANCE_TARGET,
        acceptance_meets_target=_meets_min(acceptance_rate, ACCEPTANCE_TARGET, accepted + discarded),
        valid_count=valid,
        validity_rate=validity_rate,
        validity_target=VALIDITY_TARGET,
        validity_meets_target=_meets_min(validity_rate, VALIDITY_TARGET, total),
        invalid_experiment_ids=invalid_ids,
    )


def get_report(db: Session, goal_id: str) -> EvaluationReport:
    return EvaluationReport(
        goal_id=goal_id,
        approach_usefulness=approach_usefulness(db, goal_id),
        evidence_grounding=evidence_grounding(db, goal_id),
        experiment_quality=experiment_quality(db, goal_id),
    )
