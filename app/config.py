import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    straive_api_key: str
    chat_url: str
    image_generate_url: str
    image_edit_url: str
    cad_codegen_url: str
    gemini_openai_chat_url: str
    gemini_openai_model: str
    claude_codegen_url: str
    model_name: str
    claude_model: str
    claude_project_suffix: str
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
        cad_codegen_url=os.getenv(
            "CAD_CODEGEN_URL",
            "https://llmfoundry.straivedemo.com/vertexai/google/models/gemini-2.5-pro:generateContent",
        ),
        gemini_openai_chat_url=os.getenv(
            "GEMINI_OPENAI_CHAT_URL",
            "https://llmfoundry.straive.com/gemini/v1beta/openai/chat/completions",
        ),
        gemini_openai_model=os.getenv("GEMINI_OPENAI_MODEL", "gemini-3-pro-preview"),
        claude_codegen_url=os.getenv(
            "CLAUDE_CODEGEN_URL",
            "https://llmfoundry.straive.com/anthropic/v1/messages",
        ),
        model_name=os.getenv("STRAIVE_MODEL", "gpt-5.2"),
        claude_model=os.getenv("STRAIVE_CLAUDE_MODEL", "claude-opus-4-5-20251101"),
        claude_project_suffix=os.getenv("STRAIVE_CLAUDE_PROJECT_SUFFIX", ""),
        cors_origins=origins if origins else ["*"],
        db_path=os.getenv("APP_DB_PATH", "app.db"),
        assets_dir=os.getenv("ASSETS_DIR", "assets"),
        auto_index_assets=os.getenv("AUTO_INDEX_ASSETS", "false").lower() == "true",
        cache_dir=os.getenv("CACHE_DIR", "tmp_runtime/cache"),
        session_images_dir=os.getenv("SESSION_IMAGES_DIR", "tmp_runtime/session_images"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
