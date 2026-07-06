import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.models.approach import ApproachCard
from coscientist.models.experiment import ExperimentCard
from coscientist.models.hypothesis import HypothesisCard
from coscientist.models.validation import ResultBundleReference, ValidationAggregation
from coscientist.schemas.approach import (
    ApproachExecutionEvidenceResponse,
    ApproachStatusEnum,
    ExperimentEvidenceBlock,
    NegativeEvidence,
    ValidationSummary,
)

# Forward-only status progression. `refresh_status_from_execution` only ever
# advances an approach to a higher rank, never regresses it.
_STATUS_RANK: dict[str, int] = {
    ApproachStatusEnum.generated.value: 0,
    ApproachStatusEnum.reviewed.value: 1,
    ApproachStatusEnum.scored.value: 2,
    ApproachStatusEnum.experiment_proposed.value: 3,
    ApproachStatusEnum.submitted.value: 4,
    ApproachStatusEnum.tested.value: 5,
    ApproachStatusEnum.inconclusive.value: 6,
    ApproachStatusEnum.validated.value: 7,
    ApproachStatusEnum.refuted.value: 7,
    ApproachStatusEnum.superseded.value: 8,
}

# Only approaches at or beyond scoring (and not already terminal) get their
# status refreshed from execution evidence.
_REFRESHABLE = {
    ApproachStatusEnum.scored.value,
    ApproachStatusEnum.experiment_proposed.value,
    ApproachStatusEnum.submitted.value,
    ApproachStatusEnum.tested.value,
    ApproachStatusEnum.inconclusive.value,
}


def _loads(raw: str | None, default):
    if not raw:
        return default
    return json.loads(raw)


def _approach_ids(card: ExperimentCard | ResultBundleReference) -> list[str]:
    return _loads(card.approach_ids, [])


def _experiments_for_approach(db: Session, goal_id: str, approach_id: str) -> list[ExperimentCard]:
    rows = db.scalars(
        select(ExperimentCard).where(ExperimentCard.workspace_id == goal_id)
    ).all()
    return [e for e in rows if approach_id in _approach_ids(e)]


def _validation_summary(agg: ValidationAggregation | None) -> ValidationSummary | None:
    if agg is None:
        return None
    return ValidationSummary(
        aggregate_status=agg.aggregate_status,
        total_runs=agg.total_runs,
        passed_runs=agg.passed_runs,
        failed_runs=agg.failed_runs,
        blocked_runs=agg.blocked_runs,
        missing_runs=agg.missing_runs,
        is_partial=agg.is_partial,
        metric_summaries=_loads(agg.metric_summaries, {}),
    )


def build_execution_evidence(db: Session, approach_id: str) -> ApproachExecutionEvidenceResponse:
    card = db.get(ApproachCard, approach_id)
    if card is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Approach {approach_id!r} not found")

    goal_id = card.workspace_id
    links = _loads(card.evidence_links, [])
    literature_ids = {el["evidence_id"] for el in links if el.get("evidence_type") == "direct"}
    inferred_ids = {el["evidence_id"] for el in links if el.get("evidence_type") == "inferred"}

    experiments = _experiments_for_approach(db, goal_id, approach_id)

    hypothesis_ids: set[str] = set()
    for hyp in db.scalars(select(HypothesisCard).where(HypothesisCard.workspace_id == goal_id)).all():
        if approach_id in _loads(hyp.approach_ids, []):
            hypothesis_ids.add(hyp.id)

    approved_experiments = 0
    completed_validation = 0
    failed_validation = 0
    inconclusive_validation = 0
    followups: list[str] = []

    blocks: list[ExperimentEvidenceBlock] = []
    for exp in experiments:
        if exp.execution_batch_id or _loads(exp.run_request_ids, []):
            approved_experiments += 1

        bundles = db.scalars(
            select(ResultBundleReference).where(ResultBundleReference.experiment_id == exp.id)
        ).all()

        negative: list[NegativeEvidence] = []
        bundle_ids: list[str] = []
        for rb in bundles:
            bundle_ids.append(rb.result_bundle_id)
            status = rb.validation_status
            if status == "passed":
                completed_validation += 1
            elif status == "failed":
                failed_validation += 1
            else:
                inconclusive_validation += 1

            if status != "passed":
                negative.append(
                    NegativeEvidence(
                        result_bundle_id=rb.result_bundle_id,
                        run_request_id=rb.run_request_id,
                        validation_status=status,
                        failure_type=rb.failure_type,
                        failure_summary=rb.failure_summary,
                        deviations=_loads(rb.deviations, []),
                        retryable=rb.retryable,
                    )
                )
                if rb.retryable:
                    followups.append(
                        f"Retry {exp.name}: {rb.failure_summary or rb.failure_type or 'run failed'}"
                    )
                elif rb.failure_summary or rb.failure_type:
                    followups.append(
                        f"Revise {exp.name}: {rb.failure_summary or rb.failure_type}"
                    )

        agg = db.scalar(
            select(ValidationAggregation).where(ValidationAggregation.experiment_id == exp.id)
        )

        blocks.append(
            ExperimentEvidenceBlock(
                experiment_id=exp.id,
                experiment_name=exp.name,
                status=exp.status,
                execution_status=exp.execution_status,
                execution_batch_id=exp.execution_batch_id,
                run_request_ids=_loads(exp.run_request_ids, []),
                result_bundle_ids=bundle_ids,
                validation=_validation_summary(agg),
                negative_evidence=negative,
            )
        )

    evidence_groups = {
        "source_literature": len(literature_ids),
        "inferred_synthesis": len(inferred_ids),
        "generated_hypotheses": len(hypothesis_ids),
        "approved_experiments": approved_experiments,
        "completed_validation": completed_validation,
        "failed_validation": failed_validation,
        "inconclusive_validation": inconclusive_validation,
    }

    return ApproachExecutionEvidenceResponse(
        approach_id=card.id,
        approach_name=card.name,
        status=ApproachStatusEnum(card.status),
        literature_evidence_count=len(literature_ids),
        evidence_groups=evidence_groups,
        experiments=blocks,
        suggested_followups=list(dict.fromkeys(followups)),
    )


def _target_status(db: Session, goal_id: str, approach_id: str) -> str | None:
    experiments = _experiments_for_approach(db, goal_id, approach_id)
    if not experiments:
        return None

    aggs = [
        db.scalar(select(ValidationAggregation).where(ValidationAggregation.experiment_id == e.id))
        for e in experiments
    ]
    aggs = [a for a in aggs if a is not None]

    if aggs:
        statuses = {a.aggregate_status for a in aggs}
        if "passed" in statuses:
            return ApproachStatusEnum.validated.value
        if statuses == {"failed"}:
            return ApproachStatusEnum.refuted.value
        return ApproachStatusEnum.inconclusive.value

    if any(e.execution_batch_id for e in experiments):
        return ApproachStatusEnum.submitted.value
    return ApproachStatusEnum.experiment_proposed.value


def refresh_status_from_execution(db: Session, approach_id: str) -> None:
    """Forward-only status refresh from downstream execution evidence.
    Idempotent and safe to call after every ResultBundle ingest. Flushes,
    does not commit — the caller owns the transaction."""

    card = db.get(ApproachCard, approach_id)
    if card is None or card.status not in _REFRESHABLE:
        return

    target = _target_status(db, card.workspace_id, approach_id)
    if target is None:
        return

    if _STATUS_RANK[target] > _STATUS_RANK[card.status]:
        card.status = target
        card.updated_at = datetime.now(timezone.utc)
        db.flush()
