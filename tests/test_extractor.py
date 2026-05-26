import inspect
from pathlib import Path

import pytest

from ibackupx.extractor import _query_manifest, extract_media_files, ExtractionSummary
from ibackupx import ExtractionError
from ibackupx.config import Config


def test_query_contains_camera_roll_domain():
    src = inspect.getsource(_query_manifest)
    assert "AND domain LIKE 'CameraRollDomain%'" in src


def test_extract_raises_on_encrypted_without_passphrase(tmp_path, monkeypatch):
    cfg = Config(
        backup_path=str(tmp_path),
        destination=str(tmp_path / "out"),
        organize_by_date=True,
        skip_existing=True,
        hash_size=8,
    )
    # create a manifest plist that indicates encryption
    (tmp_path / "Manifest.plist").write_text("")
    # monkeypatch is_encrypted_backup to return True
    monkeypatch.setattr('ibackupx.extractor.is_encrypted_backup', lambda bp: True)
    with pytest.raises(ExtractionError):
        extract_media_files(cfg, passphrase=None, dry_run=True)


def test_extract_allows_empty_passphrase_for_unencrypted(tmp_path, monkeypatch):
    cfg = Config(
        backup_path=str(tmp_path),
        destination=str(tmp_path / "out"),
        organize_by_date=True,
        skip_existing=True,
        hash_size=8,
    )
    monkeypatch.setattr('ibackupx.extractor.is_encrypted_backup', lambda bp: False)
    # patch _query_manifest to return empty rows
    monkeypatch.setattr('ibackupx.extractor._query_manifest', lambda conn, extensions: [])
    # should not raise even if passphrase is empty string
    extract_media_files(cfg, passphrase="", dry_run=True)


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    cfg = Config(
        backup_path=str(tmp_path),
        destination=str(tmp_path / "out"),
        organize_by_date=True,
        skip_existing=True,
        hash_size=8,
    )
    # fake two rows returned
    rows = [
        {"fileID": "aa11", "relativePath": "DCIM/1/IMG1.jpg", "domain": "CameraRollDomain", "file": None},
        {"fileID": "bb22", "relativePath": "DCIM/1/IMG2.jpg", "domain": "CameraRollDomain", "file": None},
    ]
    monkeypatch.setattr('ibackupx.extractor.is_encrypted_backup', lambda bp: False)
    monkeypatch.setattr('ibackupx.extractor._query_manifest', lambda conn, extensions: rows)
    summary = extract_media_files(cfg, passphrase=None, dry_run=True)
    assert isinstance(summary, ExtractionSummary)
    assert summary.total_extracted == 2
    # destination should not exist on disk
    assert not Path(cfg.destination).exists()
