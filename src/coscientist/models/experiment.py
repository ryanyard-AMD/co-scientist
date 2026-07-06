from datetime import datetime, timezone

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExperimentCard(Base):
    __tablename__ = "experiment_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis_text: Mapped[str] = mapped_column(Text, nullable=False)
    approach_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    hypothesis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    baseline_methods: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    independent_variables: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    fixed_assumptions: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metrics: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    validation: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    runtime: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    artifacts: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    estimated_cost: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    estimated_runtime: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    estimated_compute: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    experiment_type: Mapped[str] = mapped_column(String(32), nullable=False, default="simulation")
    parameter_sweep_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")
    generation_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Execution handoff (CS-EPIC-EXPERIMENT): execution lifecycle is tracked
    # separately from the card's approval lifecycle (`status`). The co-scientist
    # hands approved cards to the external Experimentation System as RunRequests;
    # these fields record that handoff without implying local execution.
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_submitted")
    handoff_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_submitted")
    submission_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="single_run")
    experiment_control_plane: Mapped[str | None] = mapped_column(String(256), nullable=True)
    required_capabilities: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    runner_pool_preference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_request_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    execution_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result_bundle_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    batch_expansion: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    expected_run_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_experiment_cards_workspace_id", "workspace_id"),
        Index("ix_experiment_cards_status", "status"),
        Index("ix_experiment_cards_experiment_type", "experiment_type"),
        Index("ix_experiment_cards_generation_run_id", "generation_run_id"),
        Index("ix_experiment_cards_execution_status", "execution_status"),
        Index("ix_experiment_cards_execution_batch_id", "execution_batch_id"),
    )
