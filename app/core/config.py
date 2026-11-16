from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SkillBridge Engine"
    environment: str = "development"
    debug: bool = False

    # Neon connection strings as written by `neon env pull`; app.db.url adapts them for asyncpg.
    # The app uses the pooled DATABASE_URL; Alembic uses the direct DATABASE_URL_UNPOOLED.
    database_url: SecretStr
    database_url_unpooled: SecretStr | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    db_pool_recycle: int = 300  # Neon suspends idle computes, so keep connections short-lived
    db_echo: bool = False

    gemini_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
