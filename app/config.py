import os
from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel


_cwd = Path.cwd()
ROOT = _cwd if (_cwd / "config").exists() else Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    app_env: str = "local"
    host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_port: int = 3000
    workspace_dir: Path = ROOT / "workspace"
    character_dir: Path = ROOT / "characters"
    provider_mode: str = "mock"
    vision_provider: str = "mock"
    image_provider: str = "mock"
    video_provider: str = "mock"
    composer_provider: str = "ffmpeg"
    openai_api_key: str = ""
    openai_image_model: str = "gpt-image-2"
    openai_vision_model: str = "gpt-5-mini"
    runwayml_api_secret: str = ""
    runway_api_key: str = ""
    runway_video_model: str = "seedance2"
    runway_timeout_seconds: int = 900
    relay_id: str = "kuaipao"
    relay_video_model: str = "doubao-seedance-2.0-mini-720p"
    relay_video_timeout_seconds: int = 900
    relay_video_poll_interval_seconds: float = 5.0
    allow_mock_generation: bool = False
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    max_concurrent_runs: int = 1
    max_concurrent_image_tasks: int = 2
    max_concurrent_video_tasks: int = 1
    webui_auth_enabled: bool = False
    webui_username: str = "admin"
    webui_password: str = ""
    webui_session_secret: str = ""

    def __init__(self, **data):
        env_file = ROOT / ".env"
        file_values = {}
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line and not line.lstrip().startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    file_values[key.strip()] = value.strip()
        field_names = type(self).model_fields
        for name, field in field_names.items():
            if name in data:
                continue
            env_name = name.upper()
            raw = os.environ.get(env_name, file_values.get(env_name))
            if raw is None or raw == "":
                continue
            if field.annotation is int:
                data[name] = int(raw)
            elif field.annotation is float:
                data[name] = float(raw)
            elif field.annotation is bool:
                data[name] = raw.lower() in {"1", "true", "yes", "on"}
            elif field.annotation is Path:
                path = Path(raw)
                data[name] = path if path.is_absolute() else ROOT / path
            else:
                data[name] = raw
        super().__init__(**data)

    @property
    def config_dir(self) -> Path:
        return ROOT / "config"

    @property
    def prompts_dir(self) -> Path:
        return ROOT / "prompts"

    @property
    def runway_secret(self) -> str:
        return self.runwayml_api_secret or self.runway_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
