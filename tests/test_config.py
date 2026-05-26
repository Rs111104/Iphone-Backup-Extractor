import json
from pathlib import Path

import pytest

from ibackupx import ConfigError
from ibackupx.config import Config, apply_overrides, load_config


def write_config(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def base_config(tmp_path: Path) -> dict[str, object]:
    backup = tmp_path / "backup"
    backup.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    return {
        "backup_path": str(backup),
        "destination": str(dest),
        "organize_by_date": True,
        "skip_existing": True,
    }


def test_valid_config_loads(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    write_config(cfg_path, base_config(tmp_path))
    cfg = load_config(str(cfg_path))
    assert isinstance(cfg, Config)


def test_missing_backup_path_raises_ConfigError(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    write_config(
        cfg_path,
        {
            "backup_path": str(tmp_path / "nope"),
            "destination": str(tmp_path / "out"),
            "organize_by_date": True,
            "skip_existing": True,
        },
    )
    with pytest.raises(ConfigError):
        load_config(str(cfg_path))


def test_apply_overrides_with_none_does_not_overwrite(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    write_config(cfg_path, base_config(tmp_path))
    cfg = load_config(str(cfg_path))
    new = apply_overrides(cfg, {"backup_path": None, "destination": None})
    assert new.backup_path == cfg.backup_path
    assert new.destination == cfg.destination


def test_organise_by_date_migrates(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    data = base_config(tmp_path)
    data.pop("organize_by_date")
    data["organise_by_date"] = False
    write_config(cfg_path, data)
    with pytest.warns(DeprecationWarning):
        cfg = load_config(str(cfg_path))
    assert cfg.organize_by_date is False
    migrated = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "organise_by_date" not in migrated
    assert migrated["organize_by_date"] is False
