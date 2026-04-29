"""Environment configuration for the Listmonk MCP bridge."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Runtime settings loaded from LISTMONK_MCP_* environment variables."""

    url: str = Field(..., description="Base URL of the Listmonk instance")
    username: str = Field(..., description="Listmonk API username")
    password: str = Field(..., description="Listmonk API token or password")
    timeout: int = Field(default=30, ge=1, description="HTTP timeout in seconds")
    max_retries: int = Field(default=3, ge=0, description="HTTP retry attempts")
    debug: bool = Field(default=False, description="Enable debug logging")
    log_level: str = Field(default="INFO", description="Python logging level")
    server_name: str = Field(
        default="Listmonk MCP Bridge", description="MCP server name"
    )

    model_config = SettingsConfigDict(
        env_prefix="LISTMONK_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return value.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Invalid log level")
        return level


_config: Config | None = None


def load_config(env_file: str | None = None) -> Config:
    """Load settings and cache them for subsequent calls."""

    global _config
    if env_file and Path(env_file).exists():

        class FileConfig(Config):
            model_config = Config.model_config.copy()
            model_config["env_file"] = env_file

        _config = FileConfig()  # type: ignore[call-arg]
    else:
        _config = Config()  # type: ignore[call-arg]
    return _config


def get_config() -> Config:
    """Return cached settings, loading them from the environment if needed."""

    global _config
    if _config is None:
        _config = load_config()
    return _config


def validate_config() -> None:
    """Raise when required settings are missing."""

    config = get_config()
    missing = [
        name
        for name, value in {
            "LISTMONK_MCP_URL": config.url,
            "LISTMONK_MCP_USERNAME": config.username,
            "LISTMONK_MCP_PASSWORD": config.password,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")
