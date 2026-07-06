"""Device Concept updates from execution evidence (CS-EPIC-DEVICE).

Read-aggregation over downstream execution objects plus a deterministic,
idempotent confidence/risk refresh. Recompute-from-scratch (not delta
accumulation) keeps confidence a pure function of the current validation
aggregations, so replayed ResultBundle ingestions never drift the value.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.models.device import DeviceConceptCard, DeviceEvidenceUpdate
from coscientist.models.experiment import ExperimentCard
from coscientist.models.score import RubricScore
from coscientist.models.validation import ResultBundleReference, ValidationAggregation
from coscientist.schemas.device import (
    DeviceConceptStatusEnum,
    DeviceEvidenceUpdateListResponse,
    DeviceEvidenceUpdateResponse,
    DeviceExecutionEvidenceResponse,
    DeviceExperimentEvidence,
)

_BASE_CONFIDENCE = 0.5
_PASS_WEIGHT = 0.15
_FAIL_WEIGHT = 0.15
_INCONCLUSIVE_WEIGHT = 0.05
_TARGET_DIMENSION = "evidence_strength"

# Map ResultBundle failure_type keywords to canonical device risk categories
# (CS-DEVICE-008).
_RISK_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("latency", "realtime", "real_time", "real-time"), "Latency risk: real-time budget not met in validation"),
    (("robust", "seed", "perturb", "variance"), "Robustness risk: performance sensitive to conditions"),
    (("calibrat",), "Calibration burden: validation required extensive calibration"),
    (("hardware", "feasib", "compute", "resource"), "Hardware feasibility risk surfaced in validation"),
    (("leak", "low_freq", "low-freq", "lowfreq"), "Low-frequency leakage risk surfaced in validation"),
]


def _loads(raw: str | None, default):
    if not raw:
        return default
    return json.loads(raw)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _get_or_404(db: Session, device_id: str) -> DeviceConceptCard:
    card = db.get(DeviceConceptCard, device_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Device concept {device_id!r} not found")
    return card


def _relevant_experiments(db: Session, card: DeviceConceptCard) -> list[ExperimentCard]:
    """Experiments captured at generation plus any in the goal that test one of
    the device's approaches — so evidence added after generation still counts."""
    goal_id = card.workspace_id
    approach_ids = set(_loads(card.approach_ids, []))
    captured = set(_loads(card.experiment_ids, []))

    rows = db.scalars(
        select(ExperimentCard).where(ExperimentCard.workspace_id == goal_id)
    ).all()
    out: list[ExperimentCard] = []
    for e in rows:
        if e.id in captured or (approach_ids & set(_loads(e.approach_ids, []))):
            out.append(e)
    return out


def _classify(status: str | None) -> str:
    if status == "passed":
        return "passed"
    if status == "failed":
        return "failed"
    return "inconclusive"


def _risk_for(failure_type: str | None, exp_name: str, status: str) -> str:
    ft = (failure_type or "").lower()
    for keywords, label in _RISK_KEYWORDS:
        if any(k in ft for k in keywords):
            return label
    return f"Unresolved validation risk from {exp_name} ({status})"


def _affected_approach_scores(db: Session, card: DeviceConceptCard) -> dict[str, float]:
    approach_ids = _loads(card.approach_ids, [])
    if not approach_ids:
        return {}
    rows = db.scalars(
        select(RubricScore).where(
            RubricScore.approach_id.in_(approach_ids),
            RubricScore.dimension == _TARGET_DIMENSION,
        )
    ).all()
    return {r.approach_id: round(r.score, 4) for r in rows}


def build_execution_evidence(db: Session, device_id: str) -> DeviceExecutionEvidenceResponse:
    card = _get_or_404(db, device_id)
    experiments = _relevant_experiments(db, card)

    passed = failed = inconclusive = 0
    blocks: list[DeviceExperimentEvidence] = []

    for exp in experiments:
        agg = db.scalar(
            select(ValidationAggregation).where(ValidationAggregation.experiment_id == exp.id)
        )
        bundles = db.scalars(
            select(ResultBundleReference).where(ResultBundleReference.experiment_id == exp.id)
        ).all()

        status = agg.aggregate_status if agg else None
        cls = _classify(status) if agg else None
        if cls == "passed":
            passed += 1
        elif cls == "failed":
            failed += 1
        elif cls == "inconclusive":
            inconclusive += 1

        passing_metrics: dict = {}
        if agg and status == "passed":
            summaries = _loads(agg.metric_summaries, {})
            passing_metrics = {k: v.get("mean") for k, v in summaries.items()}

        failed_assumptions: list[str] = []
        for b in bundles:
            if b.validation_status != "passed":
                failed_assumptions.extend(_loads(b.deviations, []))
                if b.failure_summary:
                    failed_assumptions.append(b.failure_summary)

        blocks.append(
            DeviceExperimentEvidence(
                experiment_id=exp.id,
                experiment_name=exp.name,
                validation_status=status,
                passed_runs=agg.passed_runs if agg else 0,
                failed_runs=agg.failed_runs if agg else 0,
                total_runs=agg.total_runs if agg else 0,
                execution_batch_id=exp.execution_batch_id,
                result_bundle_ids=[b.result_bundle_id for b in bundles],
                passing_metrics=passing_metrics,
                failed_assumptions=list(dict.fromkeys(failed_assumptions)),
            )
        )

    return DeviceExecutionEvidenceResponse(
        device_id=card.id,
        device_name=card.name,
        status=DeviceConceptStatusEnum(card.status),
        confidence=card.confidence,
        passed_experiments=passed,
        failed_experiments=failed,
        inconclusive_experiments=inconclusive,
        unresolved_risks=_loads(card.unresolved_risks, []),
        experiments=blocks,
        affected_approach_scores=_affected_approach_scores(db, card),
    )


def refresh_from_execution(db: Session, device_id: str, source_key: str) -> None:
    """Recompute device confidence and unresolved risks from linked experiment
    validation aggregations. Idempotent on (source_key, device_id). Flushes,
    does not commit — the caller owns the transaction."""

    card = db.get(DeviceConceptCard, device_id)
    if card is None:
        return

    existing = db.scalar(
        select(DeviceEvidenceUpdate).where(
            DeviceEvidenceUpdate.source_key == source_key,
            DeviceEvidenceUpdate.device_id == device_id,
        )
    )
    if existing is not None:
        return

    experiments = _relevant_experiments(db, card)
    passed = failed = inconclusive = 0
    bundle_refs: list[str] = []
    new_risks: list[str] = []

    for exp in experiments:
        agg = db.scalar(
            select(ValidationAggregation).where(ValidationAggregation.experiment_id == exp.id)
        )
        if agg is None:
            continue
        cls = _classify(agg.aggregate_status)
        if cls == "passed":
            passed += 1
        elif cls == "failed":
            failed += 1
        else:
            inconclusive += 1

        bundles = db.scalars(
            select(ResultBundleReference).where(ResultBundleReference.experiment_id == exp.id)
        ).all()
        for b in bundles:
            bundle_refs.append(b.result_bundle_id)
        if cls in ("failed", "inconclusive"):
            failure_type = next((b.failure_type for b in bundles if b.failure_type), None)
            new_risks.append(_risk_for(failure_type, exp.name, agg.aggregate_status))

    if passed == 0 and failed == 0 and inconclusive == 0:
        return

    new_confidence = _clamp(
        _BASE_CONFIDENCE
        + _PASS_WEIGHT * passed
        - _FAIL_WEIGHT * failed
        - _INCONCLUSIVE_WEIGHT * inconclusive
    )
    prev_confidence = card.confidence

    existing_risks = _loads(card.unresolved_risks, [])
    added_risks = [r for r in dict.fromkeys(new_risks) if r not in existing_risks]

    if new_confidence == prev_confidence and not added_risks:
        return

    card.confidence = new_confidence
    if added_risks:
        card.unresolved_risks = json.dumps(existing_risks + added_risks)
    card.updated_at = datetime.now(timezone.utc)

    if passed and not failed:
        agg_status = "passed"
    elif failed and not passed:
        agg_status = "failed"
    elif passed or failed:
        agg_status = "mixed"
    else:
        agg_status = "inconclusive"

    delta = round(new_confidence - prev_confidence, 4)
    direction = "raised" if delta > 0 else "lowered" if delta < 0 else "unchanged"
    rationale = (
        f"Confidence {direction} to {new_confidence:.2f} from {passed} passed, "
        f"{failed} failed, {inconclusive} inconclusive experiment(s)."
    )

    update = DeviceEvidenceUpdate(
        id=str(uuid.uuid4()),
        source_key=source_key,
        workspace_id=card.workspace_id,
        device_id=card.id,
        validation_status=agg_status,
        previous_confidence=prev_confidence,
        new_confidence=new_confidence,
        confidence_delta=delta,
        passed_experiments=passed,
        failed_experiments=failed,
        inconclusive_experiments=inconclusive,
        supporting_result_bundle_refs=json.dumps(list(dict.fromkeys(bundle_refs))),
        affected_approach_ids=json.dumps(_loads(card.approach_ids, [])),
        score_deltas=json.dumps(_affected_approach_scores(db, card)),
        added_risks=json.dumps(added_risks),
        rationale=rationale,
        created_at=datetime.now(timezone.utc),
    )
    db.add(update)
    db.flush()


def refresh_devices_for_experiment(db: Session, experiment_id: str, source_key: str) -> None:
    """Refresh every device concept whose approaches/experiments include the
    given experiment. Called after a ResultBundle is ingested."""
    exp = db.get(ExperimentCard, experiment_id)
    if exp is None:
        return
    goal_id = exp.workspace_id
    exp_approaches = set(_loads(exp.approach_ids, []))

    cards = db.scalars(
        select(DeviceConceptCard).where(DeviceConceptCard.workspace_id == goal_id)
    ).all()
    for card in cards:
        if experiment_id in _loads(card.experiment_ids, []) or (
            exp_approaches & set(_loads(card.approach_ids, []))
        ):
            refresh_from_execution(db, card.id, source_key)


def _update_to_response(u: DeviceEvidenceUpdate) -> DeviceEvidenceUpdateResponse:
    return DeviceEvidenceUpdateResponse(
        id=u.id,
        device_id=u.device_id,
        workspace_id=u.workspace_id,
        validation_status=u.validation_status,
        previous_confidence=u.previous_confidence,
        new_confidence=u.new_confidence,
        confidence_delta=u.confidence_delta,
        passed_experiments=u.passed_experiments,
        failed_experiments=u.failed_experiments,
        inconclusive_experiments=u.inconclusive_experiments,
        supporting_result_bundle_refs=_loads(u.supporting_result_bundle_refs, []),
        affected_approach_ids=_loads(u.affected_approach_ids, []),
        score_deltas=_loads(u.score_deltas, {}),
        added_risks=_loads(u.added_risks, []),
        rationale=u.rationale,
        created_at=u.created_at,
    )


def list_evidence_updates(
    db: Session,
    goal_id: str,
    *,
    device_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> DeviceEvidenceUpdateListResponse:
    stmt = select(DeviceEvidenceUpdate).where(DeviceEvidenceUpdate.workspace_id == goal_id)
    if device_id is not None:
        stmt = stmt.where(DeviceEvidenceUpdate.device_id == device_id)
    all_rows = list(db.scalars(stmt.order_by(DeviceEvidenceUpdate.created_at.desc())))
    total = len(all_rows)
    page = all_rows[skip : skip + limit]
    return DeviceEvidenceUpdateListResponse(
        items=[_update_to_response(u) for u in page], total=total
    )
