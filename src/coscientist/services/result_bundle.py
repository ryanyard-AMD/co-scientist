"""ResultBundle ingestion + validation aggregation (CS-EPIC-VALIDATION).

Ingests structured ResultBundle summaries from the external Experimentation
System, links them back to co-scientist objects, and aggregates outcomes across
all runs of an Experiment Card. Ingestion is idempotent on the
(run_request_id, run_id, attempt_id) key so replayed completion events never
double-count. The co-scientist never executes; it records references.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.models.execution import RunRequestReference
from coscientist.models.experiment import ExperimentCard
from coscientist.models.validation import ResultBundleReference, ValidationAggregation
from coscientist.schemas.execution import RunRequestStatusEnum, RunStatusUpdate
from coscientist.schemas.validation import (
    BundleValidationStatusEnum,
    MetricSummary,
    ResultBundleIngest,
    ResultBundleIngestResponse,
    ResultBundleResponse,
    ValidationAggregateStatusEnum,
    ValidationAggregationResponse,
)
from coscientist.schemas.governance import ExecutionAuditActionEnum
from coscientist.services import approach_evidence as approach_evidence_svc
from coscientist.services import execution as execution_svc
from coscientist.services import governance as governance_svc
from coscientist.services import score_update as score_update_svc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ingestion_key(body: ResultBundleIngest) -> str:
    return f"{body.run_request_id}|{body.run_id or ''}|{body.attempt_id or ''}"


# Bundle validation status -> external run execution status.
_BUNDLE_TO_RUN_STATUS = {
    BundleValidationStatusEnum.passed: RunRequestStatusEnum.completed,
    BundleValidationStatusEnum.failed: RunRequestStatusEnum.failed,
    BundleValidationStatusEnum.blocked: RunRequestStatusEnum.blocked,
    BundleValidationStatusEnum.partial: RunRequestStatusEnum.running,
    BundleValidationStatusEnum.inconclusive: RunRequestStatusEnum.completed,
}


def _bundle_to_response(b: ResultBundleReference) -> ResultBundleResponse:
    return ResultBundleResponse(
        id=b.id,
        result_bundle_id=b.result_bundle_id,
        run_request_id=b.run_request_id,
        run_id=b.run_id,
        attempt_id=b.attempt_id,
        experiment_id=b.experiment_id,
        goal_id=b.goal_id,
        hypothesis_id=b.hypothesis_id,
        approach_ids=json.loads(b.approach_ids) if b.approach_ids else [],
        execution_batch_id=b.execution_batch_id,
        validation_status=BundleValidationStatusEnum(b.validation_status),
        metrics=json.loads(b.metrics) if b.metrics else {},
        artifacts=json.loads(b.artifacts) if b.artifacts else {},
        deviations=json.loads(b.deviations) if b.deviations else [],
        warnings=json.loads(b.warnings) if b.warnings else [],
        provenance=json.loads(b.provenance) if b.provenance else {},
        failure_type=b.failure_type,
        failure_summary=b.failure_summary,
        retryable=b.retryable,
        is_partial=b.is_partial,
        created_at=b.created_at,
    )


def _agg_to_response(a: ValidationAggregation) -> ValidationAggregationResponse:
    summaries = json.loads(a.metric_summaries) if a.metric_summaries else {}
    return ValidationAggregationResponse(
        id=a.id,
        experiment_id=a.experiment_id,
        goal_id=a.goal_id,
        execution_batch_id=a.execution_batch_id,
        aggregate_status=ValidationAggregateStatusEnum(a.aggregate_status),
        expected_run_count=a.expected_run_count,
        total_runs=a.total_runs,
        passed_runs=a.passed_runs,
        failed_runs=a.failed_runs,
        blocked_runs=a.blocked_runs,
        missing_runs=a.missing_runs,
        is_partial=a.is_partial,
        metric_summaries={k: MetricSummary(**v) for k, v in summaries.items()},
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def _get_experiment_or_404(db: Session, experiment_id: str) -> ExperimentCard:
    card = db.get(ExperimentCard, experiment_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id!r} not found")
    return card


def _as_aware(dt: datetime) -> datetime:
    """SQLite may return naive datetimes; treat them as UTC for ordering."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _latest_bundle_per_run(bundles: list[ResultBundleReference]) -> list[ResultBundleReference]:
    """Collapse to one bundle per RunRequest — the latest attempt wins."""
    latest: dict[str, ResultBundleReference] = {}
    for b in sorted(bundles, key=lambda x: _as_aware(x.created_at)):
        latest[b.run_request_id] = b
    return list(latest.values())


def _aggregate_status(
    total: int, passed: int, failed: int, blocked: int, missing: int
) -> ValidationAggregateStatusEnum:
    if total == 0:
        return ValidationAggregateStatusEnum.inconclusive
    if missing > 0:
        return ValidationAggregateStatusEnum.partial
    if passed and not failed and not blocked:
        return ValidationAggregateStatusEnum.passed
    if failed and not passed and not blocked:
        return ValidationAggregateStatusEnum.failed
    if blocked and not passed and not failed:
        return ValidationAggregateStatusEnum.blocked
    if passed or failed:
        return ValidationAggregateStatusEnum.mixed
    return ValidationAggregateStatusEnum.inconclusive


def _metric_summaries(bundles: list[ResultBundleReference]) -> dict[str, dict]:
    collected: dict[str, list[float]] = {}
    for b in bundles:
        metrics = json.loads(b.metrics) if b.metrics else {}
        for name, value in metrics.items():
            if isinstance(value, (int, float)):
                collected.setdefault(name, []).append(float(value))
    summaries: dict[str, dict] = {}
    for name, values in collected.items():
        summaries[name] = {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        }
    return summaries


def recompute_aggregation(db: Session, experiment_id: str) -> ValidationAggregation:
    card = _get_experiment_or_404(db, experiment_id)
    goal_id = card.workspace_id
    all_bundles = list(
        db.scalars(
            select(ResultBundleReference).where(
                ResultBundleReference.experiment_id == experiment_id
            )
        )
    )
    bundles = _latest_bundle_per_run(all_bundles)

    total = len(bundles)
    passed = sum(1 for b in bundles if b.validation_status == BundleValidationStatusEnum.passed.value)
    failed = sum(1 for b in bundles if b.validation_status == BundleValidationStatusEnum.failed.value)
    blocked = sum(1 for b in bundles if b.validation_status == BundleValidationStatusEnum.blocked.value)
    expected = card.expected_run_count
    missing = max(0, expected - total) if expected else 0
    agg_status = _aggregate_status(total, passed, failed, blocked, missing)
    is_partial = missing > 0 or any(b.is_partial for b in bundles)

    agg = db.scalar(
        select(ValidationAggregation).where(
            ValidationAggregation.experiment_id == experiment_id
        )
    )
    if agg is None:
        agg = ValidationAggregation(
            id=str(uuid.uuid4()),
            experiment_id=experiment_id,
            goal_id=goal_id,
            created_at=_utcnow(),
        )
        db.add(agg)

    agg.goal_id = goal_id
    agg.execution_batch_id = card.execution_batch_id
    agg.aggregate_status = agg_status.value
    agg.expected_run_count = expected
    agg.total_runs = total
    agg.passed_runs = passed
    agg.failed_runs = failed
    agg.blocked_runs = blocked
    agg.missing_runs = missing
    agg.is_partial = is_partial
    agg.metric_summaries = json.dumps(_metric_summaries(bundles))
    agg.updated_at = _utcnow()
    db.flush()
    return agg


def _sync_run_request_status(db: Session, body: ResultBundleIngest) -> None:
    ref = db.scalar(
        select(RunRequestReference).where(
            RunRequestReference.run_request_id == body.run_request_id
        )
    )
    if ref is None:
        return
    run_status = _BUNDLE_TO_RUN_STATUS[body.validation_status]
    execution_svc.apply_run_status_update(
        db, body.run_request_id, RunStatusUpdate(status=run_status)
    )


def ingest_result_bundle(db: Session, body: ResultBundleIngest) -> ResultBundleIngestResponse:
    card = _get_experiment_or_404(db, body.experiment_id)
    goal_id = card.workspace_id
    key = _ingestion_key(body)

    existing = db.scalar(
        select(ResultBundleReference).where(ResultBundleReference.ingestion_key == key)
    )
    if existing is not None:
        agg = recompute_aggregation(db, body.experiment_id)
        db.commit()
        db.refresh(existing)
        db.refresh(agg)
        return ResultBundleIngestResponse(
            ingested=False,
            duplicate=True,
            bundle=_bundle_to_response(existing),
            aggregation=_agg_to_response(agg),
        )

    bundle = ResultBundleReference(
        id=str(uuid.uuid4()),
        ingestion_key=key,
        result_bundle_id=body.result_bundle_id,
        run_request_id=body.run_request_id,
        run_id=body.run_id,
        attempt_id=body.attempt_id,
        experiment_id=body.experiment_id,
        goal_id=goal_id,
        hypothesis_id=body.hypothesis_id or card.hypothesis_id,
        approach_ids=json.dumps(body.approach_ids or (json.loads(card.approach_ids) if card.approach_ids else [])),
        execution_batch_id=body.execution_batch_id or card.execution_batch_id,
        validation_status=body.validation_status.value,
        metrics=json.dumps(body.metrics),
        artifacts=json.dumps(body.artifacts),
        deviations=json.dumps(body.deviations),
        warnings=json.dumps(body.warnings),
        provenance=json.dumps(body.provenance),
        failure_type=body.failure_type,
        failure_summary=body.failure_summary,
        retryable=body.retryable,
        is_partial=body.is_partial,
        created_at=_utcnow(),
    )
    db.add(bundle)
    db.flush()

    _sync_run_request_status(db, body)
    agg = recompute_aggregation(db, body.experiment_id)

    governance_svc.record_execution_event(
        db,
        workspace_id=goal_id,
        action=ExecutionAuditActionEnum.result_bundle_ingested,
        experiment_id=body.experiment_id,
        execution_batch_id=bundle.execution_batch_id,
        run_request_ids=[body.run_request_id],
        payload_checksum=governance_svc.payload_checksum(
            {
                "result_bundle_id": body.result_bundle_id,
                "run_request_id": body.run_request_id,
                "validation_status": body.validation_status.value,
                "metrics": body.metrics,
            }
        ),
        detail={
            "result_bundle_id": body.result_bundle_id,
            "validation_status": body.validation_status.value,
        },
    )

    score_update_svc.apply_execution_score_update(
        db,
        experiment_id=body.experiment_id,
        source_key=key,
        result_bundle_id=body.result_bundle_id,
    )

    for approach_id in json.loads(bundle.approach_ids) if bundle.approach_ids else []:
        approach_evidence_svc.refresh_status_from_execution(db, approach_id)

    db.commit()
    db.refresh(bundle)
    db.refresh(agg)
    return ResultBundleIngestResponse(
        ingested=True,
        duplicate=False,
        bundle=_bundle_to_response(bundle),
        aggregation=_agg_to_response(agg),
    )


def get_aggregation(db: Session, experiment_id: str) -> ValidationAggregationResponse:
    _get_experiment_or_404(db, experiment_id)
    agg = db.scalar(
        select(ValidationAggregation).where(
            ValidationAggregation.experiment_id == experiment_id
        )
    )
    if agg is None:
        raise HTTPException(
            status_code=404,
            detail=f"No validation aggregation for experiment {experiment_id!r}",
        )
    return _agg_to_response(agg)


def list_bundles(db: Session, experiment_id: str) -> tuple[list[ResultBundleResponse], int]:
    _get_experiment_or_404(db, experiment_id)
    rows = db.scalars(
        select(ResultBundleReference)
        .where(ResultBundleReference.experiment_id == experiment_id)
        .order_by(ResultBundleReference.created_at)
    ).all()
    return [_bundle_to_response(r) for r in rows], len(rows)
