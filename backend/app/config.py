from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 位于 backend/ 目录，用绝对路径定位，避免受启动时工作目录影响。
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    # 可选：自定义 Anthropic 兼容端点。留空则走官方 API。
    # 使用本地代理时填代理地址，如: http://127.0.0.1:23333/api/anthropic
    anthropic_base_url: str = ""
    claude_model: str = "claude-sonnet-4.6"
    cors_origins: str = "http://localhost:5173"
    # 自动修订循环最大轮数（阶段 5）；0 表示只审不改。
    review_retries: int = 1

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
