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
    triposr_command: str
    triposr_output_dir: str
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
        auto_index_assets=os.getenv("AUTO_INDEX_ASSETS", "true").lower() == "true",
        triposr_command=os.getenv("TRIPOSR_COMMAND", ""),
        triposr_output_dir=os.getenv("TRIPOSR_OUTPUT_DIR", "preview_3d"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
