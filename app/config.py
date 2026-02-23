import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    straive_api_key: str
    chat_url: str
    image_generate_url: str
    image_edit_url: str
    model_name: str
    cors_origins: list[str]
    db_path: str
    assets_dir: str
    auto_index_assets: bool
    cache_dir: str
    session_images_dir: str
    log_level: str



def load_settings() -> Settings:
    origins_raw = os.getenv("CORS_ORIGINS", "*")
    origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
    return Settings(
        straive_api_key=os.getenv("STRAIVE_API_KEY", ""),
        chat_url="https://llmfoundry.straive.com/openai/v1/chat/completions",
        image_generate_url="https://llmfoundry.straive.com/openai/v1/images/generations",
        image_edit_url="https://llmfoundry.straive.com/openai/v1/images/edits",
        model_name=os.getenv("STRAIVE_MODEL", "gpt-4o-mini"),
        cors_origins=origins if origins else ["*"],
        db_path=os.getenv("APP_DB_PATH", "app.db"),
        assets_dir=os.getenv("ASSETS_DIR", "assets"),
        auto_index_assets=os.getenv("AUTO_INDEX_ASSETS", "false").lower() == "true",
        cache_dir=os.getenv("CACHE_DIR", "/tmp/pack_design_cache"),
        session_images_dir=os.getenv("SESSION_IMAGES_DIR", "/tmp/pack_design_session_images"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
