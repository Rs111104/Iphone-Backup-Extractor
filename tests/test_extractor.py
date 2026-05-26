import inspect
from datetime import datetime
from pathlib import Path

import piexif
import pytest
from PIL import Image

from ibackupx import ExtractionError
from ibackupx.config import Config
from ibackupx.extractor import (
    _destination_for_file,
    _normalise_timestamp,
    _query_manifest,
    ExtractionSummary,
    extract_media_files,
)


def test_query_contains_camera_roll_domain() -> None:
    src = inspect.getsource(_query_manifest)
    assert "AND domain LIKE 'CameraRollDomain%'" in src


def test_extract_raises_on_encrypted_without_passphrase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(
        backup_path=str(tmp_path),
        destination=str(tmp_path / "out"),
        organize_by_date=True,
        skip_existing=True,
    )
    # create a manifest plist that indicates encryption
    (tmp_path / "Manifest.plist").write_text("")
    # monkeypatch is_encrypted_backup to return True
    monkeypatch.setattr('ibackupx.extractor.is_encrypted_backup', lambda bp: True)
    with pytest.raises(ExtractionError):
        extract_media_files(cfg, passphrase=None, dry_run=True)


def test_extract_allows_empty_passphrase_for_unencrypted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(
        backup_path=str(tmp_path),
        destination=str(tmp_path / "out"),
        organize_by_date=True,
        skip_existing=True,
    )
    monkeypatch.setattr('ibackupx.extractor.is_encrypted_backup', lambda bp: False)
    # patch _query_manifest to return empty rows
    monkeypatch.setattr('ibackupx.extractor._query_manifest', lambda conn, extensions: [])
    # should not raise even if passphrase is empty string
    extract_media_files(cfg, passphrase="", dry_run=True)


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(
        backup_path=str(tmp_path),
        destination=str(tmp_path / "out"),
        organize_by_date=True,
        skip_existing=True,
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


def test_destination_for_file_uses_exif(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    source = tmp_path / "img.jpg"

    img = Image.new("RGB", (10, 10), color="red")
    img.save(source)

    exif_dict = {"Exif": {piexif.ExifIFD.DateTimeOriginal: "2020:01:02 03:04:05"}}
    exif_bytes = piexif.dump(exif_dict)
    img.save(source, exif=exif_bytes)

    path = _destination_for_file(
        source,
        destination_root=dest,
        organize_by_date=True,
        last_modified=None,
    )

    assert path.parts[-3:] == ("2020", "01", "img.jpg")


def test_destination_for_file_uses_undated(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    source = tmp_path / "img.jpg"
    source.write_text("data", encoding="utf-8")

    path = _destination_for_file(
        source,
        destination_root=dest,
        organize_by_date=True,
        last_modified=None,
    )

    assert path.parts[-2:] == ("undated", "img.jpg")


def test_normalise_timestamp_handles_ms() -> None:
    assert _normalise_timestamp(1700000000) == 1700000000
    assert _normalise_timestamp(1700000000000) == 1700000000
