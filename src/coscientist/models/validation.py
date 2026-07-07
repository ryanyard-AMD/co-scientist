from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    goal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approach_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reproduction_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="failed"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    criterion_results: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    refinement_suggestions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    measured_metrics: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    artifact_paths: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_validation_results_experiment_id", "experiment_id"),
        Index("ix_validation_results_approach_id", "approach_id"),
        Index("ix_validation_results_goal_id", "goal_id"),
    )


class ResultBundleReference(Base):
    """Co-scientist-side reference to a ResultBundle produced by the external
    Experimentation System (CS-EPIC-VALIDATION). Idempotent on the
    (run_request_id, run_id, attempt_id) ingestion key."""

    __tablename__ = "result_bundle_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ingestion_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    result_bundle_id: Mapped[str] = mapped_column(String(128), nullable=False)
    run_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    goal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    hypothesis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approach_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    execution_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    validation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="inconclusive")
    metrics: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    artifacts: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # CS-VALIDATION-013: artifact manifest link + permission-aware access labels.
    manifest_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    artifact_visibility: Mapped[str] = mapped_column(String(24), nullable=False, default="internal")
    access_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deviations: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    warnings: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    provenance: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    failure_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_result_bundle_references_experiment_id", "experiment_id"),
        Index("ix_result_bundle_references_goal_id", "goal_id"),
        Index("ix_result_bundle_references_run_request_id", "run_request_id"),
        Index("ix_result_bundle_references_execution_batch_id", "execution_batch_id"),
    )


class ValidationAggregation(Base):
    """Aggregate validation outcome across all ResultBundles of one Experiment
    Card (sweeps, seeds, ablations) — CS-VALIDATION-011. One row per experiment."""

    __tablename__ = "validation_aggregations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    goal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    execution_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    aggregate_status: Mapped[str] = mapped_column(String(16), nullable=False, default="inconclusive")
    expected_run_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    metric_summaries: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_validation_aggregations_goal_id", "goal_id"),
    )
