import json
import shutil
import tempfile
from pathlib import Path

import pytest

from ibackupx.config import load_config, apply_overrides, Config
from ibackupx import ConfigError


def write_config(path: Path, data: dict):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_valid_config_example_loads(tmp_path):
    src = Path("config.example.json")
    dst = tmp_path / "config.json"
    shutil.copy(src, dst)
    # Ensure the backup_path points to a real folder so validation passes
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    data = json.loads(dst.read_text(encoding="utf-8"))
    data["backup_path"] = str(backup_dir)
    data["destination"] = str(tmp_path / "out")
    dst.write_text(json.dumps(data), encoding="utf-8")
    # Should not raise
    cfg = load_config(str(dst))
    assert isinstance(cfg, Config)


def test_missing_backup_path_raises_ConfigError(tmp_path):
    cfg_path = tmp_path / "config.json"
    write_config(cfg_path, {"backup_path": str(tmp_path / 'nope'), "destination": str(tmp_path / 'out'), "organize_by_date": True, "skip_existing": True})
    with pytest.raises(ConfigError):
        load_config(str(cfg_path))


def test_apply_overrides_with_none_does_not_overwrite(tmp_path):
    cfg_path = tmp_path / "config.json"
    backup = tmp_path / "backup"
    backup.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    write_config(cfg_path, {"backup_path": str(backup), "destination": str(dest), "organize_by_date": True, "skip_existing": True})
    cfg = load_config(str(cfg_path))
    new = apply_overrides(cfg, {"backup_path": None, "destination": None})
    assert new.backup_path == cfg.backup_path
    assert new.destination == cfg.destination


def test_organize_by_date_string_true_coerced(tmp_path):
    cfg_path = tmp_path / "config.json"
    backup = tmp_path / "backup"
    backup.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    write_config(cfg_path, {"backup_path": str(backup), "destination": str(dest), "organize_by_date": "true", "skip_existing": True})
    cfg = load_config(str(cfg_path))
    assert cfg.organize_by_date is True
