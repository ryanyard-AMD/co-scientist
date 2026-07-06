"""Roadmap updates driven by execution outcomes (CS-EPIC-ROADMAP).

When ResultBundles for an Experiment Card aggregate, the roadmap reacts:
  * CS-ROADMAP-006 — linked roadmap items pick up the validation outcome
    (passed / failed / inconclusive) and advance their lifecycle status.
  * CS-ROADMAP-007 — a failed experiment spawns actionable follow-up items
    (rerun with changed assumptions, add baseline, inspect artifacts, adjust
    metric, test a simpler scenario).
  * CS-ROADMAP-008 — every item is re-ranked with a validation-aware score that
    folds in outcome, information gain, cost, risk, device relevance, and open
    evidence gaps.
  * CS-ROADMAP-009 — a still-incomplete (partial) batch produces *provisional*
    updates that are confirmed or replaced once the batch finishes.

The whole refresh is a deterministic projection of the current
ValidationAggregation state, so a replayed ResultBundle ingestion is idempotent:
re-running it neither double-creates follow-ups nor drifts ranks.
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.models.experiment import ExperimentCard
from coscientist.models.roadmap import ResearchRoadmapItem
from coscientist.models.validation import ValidationAggregation
from coscientist.schemas.roadmap import (
    RoadmapExecutionOutcomeEnum,
    RoadmapStatusEnum,
)
from coscientist.services import roadmap as roadmap_svc

# Marker used as generation_run_id for auto-generated failure follow-ups so they
# can be found, deduped, and re-ranked as a group.
_FOLLOWUP_RUN_ID = "execution-followup"

# ValidationAggregation.aggregate_status -> roadmap execution outcome.
_STATUS_TO_OUTCOME = {
    "passed": RoadmapExecutionOutcomeEnum.passed,
    "failed": RoadmapExecutionOutcomeEnum.failed,
    "partial": RoadmapExecutionOutcomeEnum.partial,
    "blocked": RoadmapExecutionOutcomeEnum.inconclusive,
    "mixed": RoadmapExecutionOutcomeEnum.inconclusive,
    "inconclusive": RoadmapExecutionOutcomeEnum.inconclusive,
}

# (title, description, lane, estimated_cost, estimated_information_gain)
_FAILURE_FOLLOWUPS = [
    (
        "Rerun experiment with changed assumptions",
        "Re-run the failed experiment after revising the assumptions or parameters "
        "that most likely drove the failure.",
        "exploratory",
        "medium",
        "high",
    ),
    (
        "Add a baseline comparison",
        "Introduce a known baseline so the failed result can be interpreted "
        "relative to an established reference.",
        "conservative",
        "low",
        "medium",
    ),
    (
        "Inspect failure artifacts",
        "Examine the logs, plots, and artifacts from the failed run to localise the "
        "root cause before spending on another run.",
        "conservative",
        "low",
        "medium",
    ),
    (
        "Adjust target metric or tolerance",
        "Revisit whether the target metric or pass/fail tolerance was appropriate "
        "for this experiment.",
        "conservative",
        "low",
        "medium",
    ),
    (
        "Test a simpler scenario",
        "Reduce the experiment to a simpler, cheaper scenario to isolate whether the "
        "approach works at all before scaling back up.",
        "conservative",
        "low",
        "medium",
    ),
]

# Validation-aware ranking adjustments (CS-ROADMAP-008).
_OUTCOME_ADJ = {
    RoadmapExecutionOutcomeEnum.passed.value: -0.15,
    RoadmapExecutionOutcomeEnum.failed.value: 0.10,
    RoadmapExecutionOutcomeEnum.inconclusive.value: 0.10,
    RoadmapExecutionOutcomeEnum.partial.value: 0.05,
}
_GAIN_ADJ = {"high": 0.10, "medium": 0.0, "low": -0.05}
_COST_ADJ = {"high": 0.10, "medium": 0.05, "low": 0.0}
_LANE_ADJ = {"conservative": 0.02, "device_prototype": 0.0, "exploratory": -0.02}
_FOLLOWUP_BOOST = 0.15
_PROVISIONAL_PENALTY = 0.10
_DEVICE_RELEVANCE_BOOST = 0.05
_GAP_BOOST = 0.05
_TERMINAL_PENALTY = 0.50


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def refresh_roadmap_for_experiment(db: Session, experiment_id: str) -> None:
    """React to the current aggregate validation outcome for one experiment.

    Flushes but does not commit — the caller (ResultBundle ingest) owns the
    transaction boundary.
    """
    agg = db.scalar(
        select(ValidationAggregation).where(
            ValidationAggregation.experiment_id == experiment_id
        )
    )
    if agg is None:
        return

    goal_id = agg.goal_id
    outcome = _STATUS_TO_OUTCOME.get(
        agg.aggregate_status, RoadmapExecutionOutcomeEnum.inconclusive
    )
    is_partial = agg.is_partial or outcome == RoadmapExecutionOutcomeEnum.partial
    now = _utcnow()

    _apply_outcome_to_linked_items(db, experiment_id, outcome, is_partial, now)
    _manage_followups(db, experiment_id, goal_id, agg, outcome, is_partial, now)
    # Flush new follow-ups so the re-ranking query below sees them (the session
    # runs with autoflush disabled).
    db.flush()
    _rerank_with_evidence(db, goal_id)
    db.flush()


def _apply_outcome_to_linked_items(
    db: Session,
    experiment_id: str,
    outcome: RoadmapExecutionOutcomeEnum,
    is_partial: bool,
    now: datetime,
) -> None:
    """CS-ROADMAP-006: carry the validation outcome onto items that planned this
    experiment. Forward-only — items already completed/superseded stay put, and
    auto-generated follow-ups are not treated as their own planners."""
    items = list(
        db.scalars(
            select(ResearchRoadmapItem).where(
                ResearchRoadmapItem.source_experiment_id == experiment_id,
                ResearchRoadmapItem.generation_run_id != _FOLLOWUP_RUN_ID,
                ResearchRoadmapItem.status == RoadmapStatusEnum.open.value,
            )
        )
    )
    for item in items:
        item.execution_outcome = outcome.value
        item.updated_at = now
        if is_partial:
            # Provisional signal — keep the item open pending the final batch.
            item.provisional = True
            continue
        item.provisional = False
        if outcome in (
            RoadmapExecutionOutcomeEnum.passed,
            RoadmapExecutionOutcomeEnum.failed,
        ):
            # The planned experiment has concluded; the item's work is done.
            # Failures hand off their next steps to the follow-up items below.
            item.status = RoadmapStatusEnum.completed.value


def _manage_followups(
    db: Session,
    experiment_id: str,
    goal_id: str,
    agg: ValidationAggregation,
    outcome: RoadmapExecutionOutcomeEnum,
    is_partial: bool,
    now: datetime,
) -> None:
    """CS-ROADMAP-007 + CS-ROADMAP-009: create/confirm/replace failure follow-ups."""
    existing = list(
        db.scalars(
            select(ResearchRoadmapItem).where(
                ResearchRoadmapItem.source_experiment_id == experiment_id,
                ResearchRoadmapItem.generation_run_id == _FOLLOWUP_RUN_ID,
            )
        )
    )

    early_failure = is_partial and agg.failed_runs > 0
    final_failure = (not is_partial) and outcome == RoadmapExecutionOutcomeEnum.failed

    if early_failure or final_failure:
        _create_missing_followups(
            db, experiment_id, goal_id, existing, provisional=is_partial, now=now
        )
        if final_failure:
            # Confirm provisional follow-ups spawned earlier by the partial batch.
            for item in existing:
                if item.provisional and item.status == RoadmapStatusEnum.open.value:
                    item.provisional = False
                    item.updated_at = now
    elif not is_partial:
        # Final outcome is not a failure — the early failure signal was wrong.
        # Replace any provisional follow-ups it produced.
        for item in existing:
            if item.provisional and item.status == RoadmapStatusEnum.open.value:
                item.status = RoadmapStatusEnum.superseded.value
                item.provisional = False
                item.updated_at = now


def _create_missing_followups(
    db: Session,
    experiment_id: str,
    goal_id: str,
    existing: list[ResearchRoadmapItem],
    provisional: bool,
    now: datetime,
) -> None:
    existing_titles = {i.title for i in existing}
    card = db.get(ExperimentCard, experiment_id)
    exp_name = card.name if card else experiment_id
    approach_ids = (
        card.approach_ids if (card and card.approach_ids) else "[]"
    )
    for title, description, lane, cost, gain in _FAILURE_FOLLOWUPS:
        if title in existing_titles:
            continue
        item = ResearchRoadmapItem(
            id=str(uuid.uuid4()),
            workspace_id=goal_id,
            title=title,
            description=description,
            lane=lane,
            status=RoadmapStatusEnum.open.value,
            priority_score=0.75,
            priority_rank=0,
            rationale=(
                f"Auto-generated follow-up after experiment {exp_name!r} "
                f"failed validation."
            ),
            estimated_cost=cost,
            estimated_information_gain=gain,
            source_approach_ids=approach_ids,
            source_experiment_id=experiment_id,
            source_device_id=None,
            generation_run_id=_FOLLOWUP_RUN_ID,
            model_used=None,
            provisional=provisional,
            created_at=now,
            updated_at=now,
        )
        db.add(item)


def _rerank_with_evidence(db: Session, goal_id: str) -> None:
    """CS-ROADMAP-008: recompute each item's validation-aware score + rank."""
    items = list(
        db.scalars(
            select(ResearchRoadmapItem).where(
                ResearchRoadmapItem.workspace_id == goal_id
            )
        )
    )
    if not items:
        return

    gap_approach_ids = {
        g.approach_id for g in roadmap_svc.identify_evidence_gaps(db, goal_id).gaps
    }

    for item in items:
        item.evidence_adjusted_score = _adjusted_score(item, gap_approach_ids)

    ordered = sorted(
        items,
        key=lambda i: (-(i.evidence_adjusted_score or 0.0), i.created_at),
    )
    for rank, item in enumerate(ordered, start=1):
        item.priority_rank = rank


def _adjusted_score(item: ResearchRoadmapItem, gap_approach_ids: set[str]) -> float:
    score = item.priority_score
    if item.execution_outcome:
        score += _OUTCOME_ADJ.get(item.execution_outcome, 0.0)
    score += _GAIN_ADJ.get(item.estimated_information_gain, 0.0)
    score -= _COST_ADJ.get(item.estimated_cost, 0.0)
    score += _LANE_ADJ.get(item.lane, 0.0)
    if item.generation_run_id == _FOLLOWUP_RUN_ID:
        score += _FOLLOWUP_BOOST
    if item.provisional:
        score -= _PROVISIONAL_PENALTY
    if item.source_device_id:
        score += _DEVICE_RELEVANCE_BOOST
    source_approaches = set(json.loads(item.source_approach_ids or "[]"))
    if source_approaches & gap_approach_ids:
        score += _GAP_BOOST
    if item.status in (RoadmapStatusEnum.completed.value, RoadmapStatusEnum.superseded.value):
        score -= _TERMINAL_PENALTY
    return _clamp(score)
