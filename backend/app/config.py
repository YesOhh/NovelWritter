import json
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 位于 backend/ 目录，用绝对路径定位，避免受启动时工作目录影响。
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_REPO_ROOT = _ENV_FILE.parent.parent
_CLAUDE_SETTINGS_FILE = _REPO_ROOT / ".claude" / "settings.json"


def _load_claude_settings_env() -> dict[str, str]:
    """读取本地 Anthropic 兼容代理配置（.claude/settings.json）作为开发期 fallback。"""
    if _ENV_FILE.exists() or not _CLAUDE_SETTINGS_FILE.exists():
        return {}
    try:
        raw = json.loads(_CLAUDE_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    env = raw.get("env", {})
    if not isinstance(env, dict):
        return {}
    return {str(k): str(v) for k, v in env.items() if v is not None}


_CLAUDE_ENV = _load_claude_settings_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = _CLAUDE_ENV.get("ANTHROPIC_API_KEY", "")
    anthropic_auth_token: str = _CLAUDE_ENV.get("ANTHROPIC_AUTH_TOKEN", "")
    # 可选：自定义 Anthropic 兼容端点。留空则走官方 API。
    # 使用本地代理时填代理地址，如: http://127.0.0.1:23333/api/anthropic
    anthropic_base_url: str = _CLAUDE_ENV.get("ANTHROPIC_BASE_URL", "")
    claude_model: str = Field(
        default=_CLAUDE_ENV.get("CLAUDE_MODEL")
        or _CLAUDE_ENV.get("ANTHROPIC_MODEL", "claude-sonnet-4.6"),
        validation_alias=AliasChoices("CLAUDE_MODEL", "ANTHROPIC_MODEL"),
    )
    cors_origins: str = "http://localhost:5173"
    # 自动修订循环最大轮数（阶段 5）；0 表示只审不改。
    review_retries: int = 1

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
