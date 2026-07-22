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
    scout_use_claims: bool = True
    scout_claims_top_k: int = 25
    # CS Phase 3: augment each record's method_families/metric_names from the
    # corpus's per-paper Method/Metric entity nodes (GraphRAG), mapped into the
    # canonical taxonomy. Purely additive over keyword classification.
    scout_use_entities: bool = True
    # Taxonomy induction grounding: feed the corpus's real Method entity nodes
    # (from sampled papers) into the induction prompt so canonical_names reconcile
    # with the GraphRAG graph. Topic clusters are gated separately because the
    # /advanced/topics/clusters endpoint recomputes k-means on demand and is slow.
    taxonomy_ground_in_corpus: bool = True
    taxonomy_use_topic_clusters: bool = False
    taxonomy_cluster_k: int = 8
    taxonomy_cluster_timeout: float = 20.0
    approach_min_evidence: int = 2
    # The revise agent occasionally returns a citation-less draft (empty or fully
    # invalid cited_evidence_ids), which the skip guard would drop. Because this is
    # stochastic, retry the agent up to this many times before skipping.
    approach_revise_max_attempts: int = 3
    hypothesis_max_per_run: int = 20
    hypothesis_complementary_high: float = 0.6
    hypothesis_complementary_low: float = 0.4
    # When true, a Claude agent synthesizes each selected approach pair into a
    # genuine research hypothesis (name, statement, rationale, reframed
    # assumptions/failure_modes/experiments) instead of templated string
    # concatenation. Falls back to deterministic synthesis when no API key.
    hypothesis_use_llm: bool = True
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
    # P4: the runner resolves which reproduction to run by asking repro's
    # recommend-method endpoint (top runnable candidate for the card's hypothesis)
    # instead of a local method_family→simulator registry.
    runner_recommend_top_k: int = 10
    # When true, drop card pass_conditions that name metrics the chosen
    # reproduction never emits (per metrics-surface), so a run is not refuted for
    # a metric it could never produce. Advisory: dropped conditions are logged.
    runner_align_pass_conditions: bool = True
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
