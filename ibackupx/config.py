"""Configuration loading and validation."""

from __future__ import annotations

import json
import os
import pathlib
import platform
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import BaseModel, ValidationError, field_validator, model_validator

from ibackupx import ConfigError


@dataclass
class Config:
    """Validated configuration for iBackupX."""

    backup_path: str
    destination: str
    organize_by_date: bool
    skip_existing: bool


def default_destination() -> str:
    """Return the platform default output folder."""

    return str(pathlib.Path.home() / "Pictures" / "iBackupX")


def default_backup_path() -> str:
    """Return the platform default iPhone backup path, if any."""

    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return ""
        return str(pathlib.Path(appdata) / "Apple Computer" / "MobileSync" / "Backup")
    if system == "Darwin":
        return str(pathlib.Path.home() / "Library" / "Application Support" / "MobileSync" / "Backup")
    return ""


def _nearest_existing_parent(path: pathlib.Path) -> Optional[pathlib.Path]:
    """Return the nearest existing parent for a path, if any."""
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current if current.exists() else None


def _ensure_writable(path: pathlib.Path) -> None:
    """Raise ConfigError if a path is not writable or cannot be created."""
    if path.exists():
        if not path.is_dir():
            raise ConfigError(f"destination is not a directory: {path}")
        if not os.access(path, os.W_OK):
            raise ConfigError(f"destination is not writable: {path}")
        return

    parent = _nearest_existing_parent(path)
    if parent is None or not parent.is_dir():
        raise ConfigError(f"destination parent does not exist: {path}")
    if not os.access(parent, os.W_OK):
        raise ConfigError(f"destination is not writable: {path}")


class ConfigModel(BaseModel):
    """Pydantic model for config validation."""

    backup_path: str = ""
    destination: str = ""
    organize_by_date: bool = True
    skip_existing: bool = True

    model_config = {"extra": "ignore"}

    @field_validator("backup_path", "destination", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> str:
        """Normalize missing or whitespace-only values."""
        if value is None:
            return ""
        return str(value).strip()

    @model_validator(mode="after")
    def _apply_defaults_and_validate(self) -> "ConfigModel":
        """Apply defaults and validate all filesystem paths."""
        if not self.backup_path:
            self.backup_path = default_backup_path()
        if not self.backup_path:
            raise ConfigError("No standard backup path exists on Linux. Set backup_path in config.json.")
        if not self.destination:
            self.destination = default_destination()

        backup_path = pathlib.Path(self.backup_path).expanduser()
        if not backup_path.exists():
            raise ConfigError(f"backup_path does not exist: {backup_path}")

        destination_path = pathlib.Path(self.destination).expanduser()
        _ensure_writable(destination_path)

        self.backup_path = str(backup_path)
        self.destination = str(destination_path)
        return self


def load_config(config_path: str) -> Config:
    """Load and validate configuration from a JSON file."""

    config_file = pathlib.Path(config_path)
    if not config_file.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        with config_file.open("r", encoding="utf-8") as handle:
            raw: Dict[str, Any] = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in config file: {config_path}") from exc

    try:
        model = ConfigModel.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc

    return Config(
        backup_path=model.backup_path,
        destination=model.destination,
        organize_by_date=model.organize_by_date,
        skip_existing=model.skip_existing,
    )


def apply_overrides(config: Config, overrides: Dict[str, Any]) -> Config:
    """Apply CLI overrides and re-validate using the pydantic model."""

    data = {
        "backup_path": overrides.get("backup_path", config.backup_path),
        "destination": overrides.get("destination", config.destination),
        "organize_by_date": overrides.get("organize_by_date", config.organize_by_date),
        "skip_existing": overrides.get("skip_existing", config.skip_existing),
    }

    try:
        model = ConfigModel.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc

    return Config(
        backup_path=model.backup_path,
        destination=model.destination,
        organize_by_date=model.organize_by_date,
        skip_existing=model.skip_existing,
    )
