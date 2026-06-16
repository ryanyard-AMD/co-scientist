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


settings = Settings()
