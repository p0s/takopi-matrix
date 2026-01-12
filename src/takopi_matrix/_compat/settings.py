"""Copied from takopi.settings - DEPRECATED.

This is a simplified version that only provides load_settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import TomlConfigSettingsSource

from .config import HOME_CONFIG_PATH, ConfigError


def _resolve_config_path(path: str | Path | None) -> Path:
    return Path(path).expanduser() if path else HOME_CONFIG_PATH


def _ensure_config_file(cfg_path: Path) -> None:
    if cfg_path.exists() and not cfg_path.is_file():
        raise ConfigError(f"Config path {cfg_path} exists but is not a file.") from None
    if not cfg_path.exists():
        raise ConfigError(f"Missing config file {cfg_path}.") from None


class TakopiSettings(BaseSettings):
    """Minimal settings class for compatibility."""

    model_config = SettingsConfigDict(
        extra="allow",
        env_prefix="TAKOPI__",
        env_nested_delimiter="__",
        str_strip_whitespace=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def load_settings(path: str | Path | None = None) -> tuple[TakopiSettings, Path]:
    """Load settings from TOML config file."""
    cfg_path = _resolve_config_path(path)
    _ensure_config_file(cfg_path)

    cfg = dict(TakopiSettings.model_config)
    cfg["toml_file"] = cfg_path
    Bound = type(
        "TakopiSettingsBound",
        (TakopiSettings,),
        {"model_config": SettingsConfigDict(**cfg)},
    )
    try:
        return Bound(), cfg_path
    except ValidationError as exc:
        raise ConfigError(f"Invalid config in {cfg_path}: {exc}") from exc
    except Exception as exc:
        raise ConfigError(f"Failed to load config {cfg_path}: {exc}") from exc
