import plistlib
from pathlib import Path

import pytest

from ibackupx.inspector import is_encrypted_backup, find_backup_dirs
from ibackupx import BackupError


def write_plist(path: Path, data: dict):
    with path.open("wb") as f:
        plistlib.dump(data, f)


def test_is_encrypted_true_for_IsEncrypted(tmp_path):
    bp = tmp_path / "backup"
    bp.mkdir()
    write_plist(bp / "Manifest.plist", {"IsEncrypted": True})
    assert is_encrypted_backup(str(bp)) is True


def test_is_encrypted_false_for_IsEncrypted_false(tmp_path):
    bp = tmp_path / "backup"
    bp.mkdir()
    write_plist(bp / "Manifest.plist", {"IsEncrypted": False})
    assert is_encrypted_backup(str(bp)) is False


def test_is_encrypted_false_for_WasPasscodeSet(tmp_path):
    bp = tmp_path / "backup"
    bp.mkdir()
    write_plist(bp / "Manifest.plist", {"WasPasscodeSet": True})
    assert is_encrypted_backup(str(bp)) is False


def test_find_backup_dirs_single(tmp_path):
    root = tmp_path / "MobileSync" / "Backup"
    root.mkdir(parents=True)
    (root / "abcd").mkdir()
    (root / "abcd" / "Manifest.db").write_text("")
    selected = find_backup_dirs(str(root))
    assert str((root / "abcd")) == selected
