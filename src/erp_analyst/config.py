from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://erp_admin:dev-only-local-password@127.0.0.1:5433/erp_analyst"
    analyst_database_url: str = "postgresql://analyst_ro:dev-only-local-password@127.0.0.1:5433/erp_analyst"

    anthropic_api_key: str = ""
    erp_model_cheap: str = "claude-haiku-5-5"
    erp_model_strong: str = "claude-sonnet-5-5"

    analyst_statement_timeout_ms: int = 5000


settings = Settings()
