from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "WORLD_"}

    app_name: str = "Edinworld Canon Engine"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://eden:eden@localhost:5432/eden"
    database_url_sync: str = "postgresql://eden:eden@localhost:5432/eden"
    db_pool_size: int = 20
    db_max_overflow: int = 10

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    extraction_batch_size: int = 10

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-reasoner"

    ollama_base_url: str = ""
    ollama_model: str = "qwen3:14b"

    worker_heartbeat_interval_seconds: int = 30
    worker_stale_threshold_seconds: int = 120
    worker_checkpoint_interval_items: int = 50
    worker_checkpoint_interval_seconds: int = 60
    worker_max_attempts: int = 3

    comfyui_url: str = ""
    cartesia_api_key: str = ""
    cartesia_voice_id: str = "5ee9feff-1265-424a-9d7f-8e4d431a12c7"
    video_r2_prefix: str = "videos"

    runpod_api_key: str = ""
    runpod_endpoint_id: str = ""
    image_r2_prefix: str = "story-images"

    api_host: str = "0.0.0.0"
    api_port: int = 8001


settings = Settings()
