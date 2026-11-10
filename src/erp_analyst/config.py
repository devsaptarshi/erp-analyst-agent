from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://erp_admin:dev-only-local-password@127.0.0.1:5433/erp_analyst"
    analyst_database_url: str = "postgresql://analyst_ro:dev-only-local-password@127.0.0.1:5433/erp_analyst"

    anthropic_api_key: str = ""
    erp_model_cheap: str = "claude-haiku-5-5"
    erp_model_strong: str = "claude-sonnet-5-5"

    # Second provider, selectable per the Week 3 build spec item ("add a
    # second model provider through config") — swap in by setting
    # erp_model_provider=openai and the two model ids below. No OpenAI API
    # key was available while building this; see KNOWN_LIMITS.md.
    erp_model_provider: str = "anthropic"  # "anthropic" | "openai"
    openai_api_key: str = ""
    erp_openai_model_cheap: str = "gpt-5-mini"
    erp_openai_model_strong: str = "gpt-5"

    analyst_statement_timeout_ms: int = 5000


settings = Settings()
