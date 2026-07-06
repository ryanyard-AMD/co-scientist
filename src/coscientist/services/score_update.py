"""Execution-evidence score updates (CS-EPIC-SCORE).

When a ResultBundle is ingested and the Experiment Card's validation aggregation
is recomputed, the linked Approach Cards' rubric confidence should move to
reflect real execution evidence — a validated pass raises confidence, a failure
lowers the score, and mixed/partial/blocked outcomes move confidence more
cautiously than clean pass/fail (CS-SCORE-011).

Each adjustment is recorded as a fully explainable ``ScoreUpdate`` (previous /
new score, deltas, ResultBundle references, aggregate run counts and metrics)
and is idempotent on the triggering ingestion key so replayed events never
double-count (CS-SCORE-010).
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.models.experiment import ExperimentCard
from coscientist.models.score import RubricScore, ScoreUpdate
from coscientist.models.validation import ValidationAggregation
from coscientist.schemas.score import (
    ScoreUpdateListResponse,
    ScoreUpdateResponse,
)

# Dimension that execution evidence informs most directly.
_TARGET_DIMENSION = "evidence_strength"

# aggregate_status -> (evidence_type, score_sign, confidence_factor).
# score_sign scales settings.score_execution_delta; confidence_factor scales
# settings.score_confidence_delta. Clean pass/fail move confidence fully (1.0);
# mixed/partial move it cautiously; blocked erodes it (CS-SCORE-011).
_OUTCOME_EFFECT: dict[str, tuple[str, float, float]] = {
    "passed": ("validation_passed", +1.0, +1.0),
    "failed": ("validation_failed", -1.0, +1.0),
    "mixed": ("mixed_validation", 0.0, +0.4),
    "partial": ("completed_experiment", 0.0, +0.2),
    "blocked": ("queued_experiment", 0.0, -0.2),
    "inconclusive": ("completed_experiment", 0.0, 0.0),
}


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _to_response(row: ScoreUpdate) -> ScoreUpdateResponse:
    return ScoreUpdateResponse(
        id=row.id,
        source_key=row.source_key,
        workspace_id=row.workspace_id,
        approach_id=row.approach_id,
        experiment_id=row.experiment_id,
        execution_batch_id=row.execution_batch_id,
        dimension=row.dimension,
        validation_status=row.validation_status,
        evidence_type=row.evidence_type,
        previous_score=row.previous_score,
        new_score=row.new_score,
        score_delta=row.score_delta,
        previous_confidence=row.previous_confidence,
        new_confidence=row.new_confidence,
        confidence_delta=row.confidence_delta,
        run_count=row.run_count,
        passed_count=row.passed_count,
        failed_count=row.failed_count,
        missing_count=row.missing_count,
        result_bundle_refs=json.loads(row.result_bundle_refs) if row.result_bundle_refs else [],
        aggregate_metrics=json.loads(row.aggregate_metrics) if row.aggregate_metrics else {},
        rationale=row.rationale,
        reviewer_notes=row.reviewer_notes,
        created_at=row.created_at,
    )


def _rationale(status: str, delta: float, conf_delta: float, agg: ValidationAggregation) -> str:
    direction = "raised" if delta > 0 else "lowered" if delta < 0 else "held"
    conf_dir = "raised" if conf_delta > 0 else "lowered" if conf_delta < 0 else "held"
    return (
        f"Validation aggregate '{status}' over {agg.total_runs} run(s) "
        f"({agg.passed_runs} passed, {agg.failed_runs} failed, {agg.missing_runs} missing): "
        f"{direction} evidence-strength score by {round(delta, 4)}, {conf_dir} confidence "
        f"by {round(conf_delta, 4)}."
    )


def apply_execution_score_update(
    db: Session,
    *,
    experiment_id: str,
    source_key: str,
    result_bundle_id: str,
    reviewer_notes: str | None = None,
) -> list[ScoreUpdate]:
    """Adjust linked approaches' evidence-strength scores from validation evidence.

    Best-effort and idempotent: approaches without an existing rubric score are
    skipped, and a (source_key, approach_id, dimension) already recorded is not
    re-applied. Flushes into the caller's transaction; does not commit.
    """
    card = db.get(ExperimentCard, experiment_id)
    if card is None:
        return []
    agg = db.scalar(
        select(ValidationAggregation).where(
            ValidationAggregation.experiment_id == experiment_id
        )
    )
    if agg is None:
        return []

    status = agg.aggregate_status
    effect = _OUTCOME_EFFECT.get(status)
    if effect is None:
        return []
    evidence_type, score_sign, conf_factor = effect

    approach_ids = json.loads(card.approach_ids) if card.approach_ids else []
    metrics = json.loads(agg.metric_summaries) if agg.metric_summaries else {}
    now = datetime.now(timezone.utc)
    created: list[ScoreUpdate] = []

    for approach_id in approach_ids:
        row = db.scalar(
            select(RubricScore).where(
                RubricScore.approach_id == approach_id,
                RubricScore.dimension == _TARGET_DIMENSION,
            )
        )
        if row is None:
            continue

        already = db.scalar(
            select(ScoreUpdate).where(
                ScoreUpdate.source_key == source_key,
                ScoreUpdate.approach_id == approach_id,
                ScoreUpdate.dimension == _TARGET_DIMENSION,
            )
        )
        if already is not None:
            continue

        prev_score = row.score
        prev_conf = row.confidence
        new_score = _clamp(prev_score + score_sign * settings.score_execution_delta)
        new_conf = _clamp((prev_conf or 0.0) + conf_factor * settings.score_confidence_delta)
        score_delta = new_score - prev_score
        conf_delta = new_conf - (prev_conf or 0.0)

        row.score = new_score
        row.confidence = new_conf
        row.weighted_score = new_score * row.weight

        update = ScoreUpdate(
            id=str(uuid.uuid4()),
            source_key=source_key,
            workspace_id=card.workspace_id,
            approach_id=approach_id,
            experiment_id=experiment_id,
            execution_batch_id=card.execution_batch_id,
            dimension=_TARGET_DIMENSION,
            validation_status=status,
            evidence_type=evidence_type,
            previous_score=prev_score,
            new_score=new_score,
            score_delta=score_delta,
            previous_confidence=prev_conf,
            new_confidence=new_conf,
            confidence_delta=conf_delta,
            run_count=agg.total_runs,
            passed_count=agg.passed_runs,
            failed_count=agg.failed_runs,
            missing_count=agg.missing_runs,
            result_bundle_refs=json.dumps([result_bundle_id]),
            aggregate_metrics=json.dumps(metrics),
            rationale=_rationale(status, score_delta, conf_delta, agg),
            reviewer_notes=reviewer_notes,
            created_at=now,
        )
        db.add(update)
        created.append(update)

    db.flush()
    return created


def list_score_updates(
    db: Session,
    goal_id: str,
    *,
    approach_id: str | None = None,
    experiment_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> ScoreUpdateListResponse:
    stmt = (
        select(ScoreUpdate)
        .where(ScoreUpdate.workspace_id == goal_id)
        .order_by(ScoreUpdate.created_at.desc())
    )
    if approach_id is not None:
        stmt = stmt.where(ScoreUpdate.approach_id == approach_id)
    if experiment_id is not None:
        stmt = stmt.where(ScoreUpdate.experiment_id == experiment_id)

    rows = list(db.scalars(stmt))
    total = len(rows)
    page = rows[skip : skip + limit]
    return ScoreUpdateListResponse(items=[_to_response(r) for r in page], total=total)
