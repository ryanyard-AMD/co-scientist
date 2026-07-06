import json

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.models.approach import ApproachCard
from coscientist.models.execution import RunAttemptReference, RunRequestReference
from coscientist.models.experiment import ExperimentCard
from coscientist.models.governance import AgentActionLog, ExecutionAuditLog
from coscientist.models.score import ScoreUpdate
from coscientist.models.validation import ResultBundleReference
from coscientist.schemas.evaluation import (
    ApproachUsefulnessMetrics,
    DuplicateIngestionMetrics,
    EvaluationReport,
    EvidenceGroundingMetrics,
    ExecutionTraceabilityMetrics,
    ExperimentQualityMetrics,
    HandoffSuccessMetrics,
    ProductivityMetrics,
    UnsupportedClaim,
)
from coscientist.services import experiment as experiment_svc
from coscientist.services import feedback as feedback_svc
from coscientist.services import goal as goal_svc

# PRD §20 Success Metrics targets.
USEFULNESS_TARGET = 0.75
TRACEABILITY_TARGET = 1.0
GROUNDING_TARGET = 0.90
UNSUPPORTED_TARGET = 0.05
ACCEPTANCE_TARGET = 0.70
VALIDITY_TARGET = 0.85
HANDOFF_SUCCESS_TARGET = 0.95

# Experiment lifecycle statuses that imply the card was approved for execution.
_EXPERIMENT_APPROVED = {"approved", "running", "completed", "failed"}
# handoff_status values that count as a submission attempt / success.
_HANDOFF_ATTEMPTED = {"submitting", "submitted", "failed", "canceled"}
_HANDOFF_SUCCEEDED = {"submitted"}
_HANDOFF_FAILED = {"failed", "canceled"}

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


def productivity(db: Session, goal_id: str) -> ProductivityMetrics:
    """Estimate research time saved and user satisfaction (CS-EVAL-005).

    Time saved is a heuristic: each successful agent action (a task a researcher
    would otherwise do by hand) is credited a configurable manual-equivalent
    duration. Satisfaction is the share of positive feedback votes.
    """
    goal_svc.get(db, goal_id)

    action_count = db.scalar(
        select(func.count())
        .select_from(AgentActionLog)
        .where(AgentActionLog.workspace_id == goal_id, AgentActionLog.error.is_(None))
    ) or 0

    minutes_per = settings.eval_minutes_per_agent_action
    minutes_saved = action_count * minutes_per

    positive, total = feedback_svc.satisfaction_counts(db, goal_id)
    satisfaction = (positive / total) if total else None

    return ProductivityMetrics(
        goal_id=goal_id,
        agent_action_count=action_count,
        minutes_per_agent_action=minutes_per,
        estimated_time_saved_minutes=minutes_saved,
        estimated_time_saved_hours=round(minutes_saved / 60, 2),
        positive_feedback=positive,
        total_feedback=total,
        satisfaction_rate=satisfaction,
    )


def handoff_success(db: Session, goal_id: str) -> HandoffSuccessMetrics:
    """CS-EVAL-007: measure RunRequest creation / handoff reliability.

    Everything is derived from stored state: the Experiment Card handoff
    lifecycle, RunRequest references, and run attempts. The co-scientist only
    records the handoff — it never runs anything.
    """
    goal_svc.get(db, goal_id)
    cards = db.scalars(
        select(ExperimentCard).where(ExperimentCard.workspace_id == goal_id)
    ).all()

    approved = attempted = successful = failed = 0
    for card in cards:
        if card.status in _EXPERIMENT_APPROVED or card.handoff_status in _HANDOFF_ATTEMPTED:
            approved += 1
        if card.handoff_status in _HANDOFF_ATTEMPTED:
            attempted += 1
        if card.handoff_status in _HANDOFF_SUCCEEDED:
            successful += 1
        if card.handoff_status in _HANDOFF_FAILED:
            failed += 1

    run_requests = db.scalars(
        select(RunRequestReference).where(RunRequestReference.goal_id == goal_id)
    ).all()
    successful_run_requests = len(run_requests)

    # Retry success: run requests that took more than one attempt and ended
    # completed. Attempt counts come from RunAttemptReference.
    retried = retry_successes = 0
    for rr in run_requests:
        attempt_count = db.scalar(
            select(func.count())
            .select_from(RunAttemptReference)
            .where(RunAttemptReference.run_request_id == rr.run_request_id)
        ) or 0
        if attempt_count >= 2:
            retried += 1
            if rr.status == "completed":
                retry_successes += 1

    handoff_rate = _rate(successful, attempted)
    retry_rate = (retry_successes / retried) if retried else None
    return HandoffSuccessMetrics(
        goal_id=goal_id,
        approved_experiments=approved,
        attempted_handoffs=attempted,
        successful_handoffs=successful,
        failed_handoffs=failed,
        handoff_success_rate=handoff_rate,
        handoff_success_target=HANDOFF_SUCCESS_TARGET,
        handoff_success_meets_target=_meets_min(handoff_rate, HANDOFF_SUCCESS_TARGET, attempted),
        successful_run_requests=successful_run_requests,
        retried_run_requests=retried,
        retry_successes=retry_successes,
        retry_success_rate=retry_rate,
    )


def execution_traceability(db: Session, goal_id: str) -> ExecutionTraceabilityMetrics:
    """CS-EVAL-008: every RunRequest should trace back to research intent —
    goal, Experiment Card, Approach Card, Hypothesis Card (where applicable),
    and an approval/handoff record."""
    goal_svc.get(db, goal_id)
    run_requests = db.scalars(
        select(RunRequestReference).where(RunRequestReference.goal_id == goal_id)
    ).all()

    # Experiment cards with a handoff-submitted audit record are "approved".
    approved_experiment_ids = set(
        db.scalars(
            select(ExecutionAuditLog.experiment_id).where(
                ExecutionAuditLog.workspace_id == goal_id,
                ExecutionAuditLog.action == "handoff_submitted",
            )
        )
    )
    approved_experiment_ids.discard(None)

    linked_goal = linked_experiment = linked_approach = 0
    hypothesis_applicable = linked_hypothesis = linked_approval = fully = 0
    untraceable: list[str] = []
    for rr in run_requests:
        has_goal = bool(rr.goal_id)
        card = db.get(ExperimentCard, rr.experiment_id)
        has_experiment = card is not None
        has_approach = bool(card and json.loads(card.approach_ids or "[]"))
        has_hypothesis_slot = bool(card and card.hypothesis_id)
        has_approval = rr.experiment_id in approved_experiment_ids

        linked_goal += has_goal
        linked_experiment += has_experiment
        linked_approach += has_approach
        if has_hypothesis_slot:
            hypothesis_applicable += 1
            linked_hypothesis += 1
        linked_approval += has_approval

        if has_goal and has_experiment and has_approach and has_approval:
            fully += 1
        else:
            untraceable.append(rr.run_request_id)

    total = len(run_requests)
    rate = _rate(fully, total)
    return ExecutionTraceabilityMetrics(
        goal_id=goal_id,
        total_run_requests=total,
        linked_to_goal=linked_goal,
        linked_to_experiment=linked_experiment,
        linked_to_approach=linked_approach,
        hypothesis_applicable=hypothesis_applicable,
        linked_to_hypothesis=linked_hypothesis,
        linked_to_approval=linked_approval,
        fully_traceable=fully,
        traceability_rate=rate,
        traceability_target=TRACEABILITY_TARGET,
        traceability_meets_target=_meets_min(rate, TRACEABILITY_TARGET, total),
        untraceable_run_request_ids=untraceable,
    )


def duplicate_ingestion(db: Session, goal_id: str) -> DuplicateIngestionMetrics:
    """CS-EVAL-009: verify idempotent ingestion — zero duplicate score changes.

    ResultBundles are unique on their ingestion key and score updates on
    (source_key, approach_id, dimension); a nonzero duplicate count means the
    idempotency guarantee was violated.
    """
    goal_svc.get(db, goal_id)

    bundle_keys = db.scalars(
        select(ResultBundleReference.ingestion_key).where(
            ResultBundleReference.goal_id == goal_id
        )
    ).all()
    total_bundles = len(bundle_keys)
    distinct_keys = len(set(bundle_keys))

    update_rows = db.execute(
        select(
            ScoreUpdate.source_key, ScoreUpdate.approach_id, ScoreUpdate.dimension
        ).where(ScoreUpdate.workspace_id == goal_id)
    ).all()
    total_updates = len(update_rows)
    distinct_updates = len({tuple(r) for r in update_rows})

    duplicate_bundles = total_bundles - distinct_keys
    duplicate_updates = total_updates - distinct_updates
    return DuplicateIngestionMetrics(
        goal_id=goal_id,
        total_result_bundles=total_bundles,
        distinct_ingestion_keys=distinct_keys,
        duplicate_bundle_count=duplicate_bundles,
        total_score_updates=total_updates,
        distinct_score_update_keys=distinct_updates,
        duplicate_score_update_count=duplicate_updates,
        meets_target=duplicate_bundles == 0 and duplicate_updates == 0,
    )


def get_report(db: Session, goal_id: str) -> EvaluationReport:
    return EvaluationReport(
        goal_id=goal_id,
        approach_usefulness=approach_usefulness(db, goal_id),
        evidence_grounding=evidence_grounding(db, goal_id),
        experiment_quality=experiment_quality(db, goal_id),
        productivity=productivity(db, goal_id),
        handoff_success=handoff_success(db, goal_id),
        execution_traceability=execution_traceability(db, goal_id),
        duplicate_ingestion=duplicate_ingestion(db, goal_id),
    )
