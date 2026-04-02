from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "EDEN_"}

    app_name: str = "Eden Ingestion Platform"
    debug: bool = False

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://eden:eden@localhost:5432/eden"
    database_url_sync: str = "postgresql://eden:eden@localhost:5432/eden"
    db_pool_size: int = 3
    db_max_overflow: int = 2

    # Cloudflare R2
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "eden-raw"

    # Embedding
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    openai_api_key: str = ""

    # Workers
    worker_heartbeat_interval_seconds: int = 30
    worker_stale_threshold_seconds: int = 120
    worker_checkpoint_interval_items: int = 50
    worker_checkpoint_interval_seconds: int = 60
    worker_max_attempts: int = 3

    # Anthropic (for context extraction)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    context_extraction_batch_size: int = 20
    context_extraction_rules_only: bool = False

    # External API keys
    europeana_api_key: str = ""

    # Rate limiting
    default_rate_limit_rpm: int = 60
    default_fetch_delay_seconds: float = 1.0

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000


settings = Settings()
