from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    node_env: Literal["development", "production", "test"] = "development"
    port: int = 3000

    database_url: str
    redis_url: str
    loki_url: str | None = None

    jwt_access_secret: str
    jwt_refresh_secret: str

    leetcode_username: str | None = None
    leetcode_session: str | None = None
    leetcode_csrf: str | None = None

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

    chroma_url: str = "http://localhost:8000"
    chroma_host: str | None = None
    chroma_api_key: str | None = None
    chroma_tenant: str | None = None
    chroma_database: str | None = None

    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_top_k: int = 5

    confidence_low: float = 0.5
    confidence_high: float = 0.8

    query_expansion_enabled: bool = True
    query_expansion_variants: int = 2
    hyde_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
