from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./coscientist.db"
    api_prefix: str = "/co-scientist"
    debug: bool = False
    port: int = 8001
    retrieval_url: str = "http://localhost:8000"
    retrieval_api_key: str | None = None


settings = Settings()
