from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./coscientist.db"
    api_prefix: str = "/co-scientist"
    debug: bool = False
    port: int = 8001
    retrieval_url: str = "http://localhost:8000"
    retrieval_api_key: str | None = None
    scout_top_k: int = 20
    scout_strong_threshold: int = 5
    scout_weak_threshold: int = 1
    scout_sparse_threshold: int = 3
    scout_min_score: float = 0.0
    scout_min_chunk_words: int = 5
    scout_include_artifacts: bool = True
    approach_min_evidence: int = 2
    hypothesis_max_per_run: int = 20
    hypothesis_complementary_high: float = 0.6
    hypothesis_complementary_low: float = 0.4
    experiment_max_per_run: int = 10
    experiment_sweep_cost_low: int = 100
    experiment_sweep_cost_medium: int = 500
    experiment_sweep_cost_high: int = 2000
    validation_model: str = "claude-sonnet-4-6"
    anthropic_api_key: str | None = None
    repro_url: str = "http://localhost:8003"
    repro_api_key: str | None = None
    repro_poll_interval: float = 2.0
    repro_run_timeout: float = 600.0
    eval_minutes_per_agent_action: int = 45
    # CS-EVAL-010: an in-flight RunRequest whose status has not updated within
    # this many seconds is flagged as stale (execution-status freshness).
    eval_status_freshness_threshold_seconds: int = 3600
    # CS-GOV-008: when true, the co-scientist refuses to execute experiments
    # itself (the direct repro runner path) — experiments run only via RunRequest
    # handoff to the external Experimentation System.
    enforce_execution_boundary: bool = False
    # CS-EPIC-SCORE: execution-evidence score update magnitudes (0..1 rubric scale).
    score_execution_delta: float = 0.15
    score_confidence_delta: float = 0.20
    # CS-VALIDATION-012: gate final approach-score updates on complete aggregations.
    # When false (default), a partial aggregation (missing runs or a partial bundle)
    # does NOT drive an approach score update — evidence is provisional until the
    # batch completes. Set true to update scores from partial evidence.
    score_update_on_partial: bool = False


settings = Settings()
