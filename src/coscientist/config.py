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


settings = Settings()
