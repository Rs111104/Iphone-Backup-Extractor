from datetime import datetime
from pathlib import Path

import pytest

from ibackupx import deduplicator


def test_remove_duplicates_keeps_newest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    older = tmp_path / "older.jpg"
    newer = tmp_path / "newer.jpg"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")

    entries = [
        deduplicator.FileEntry(
            path=older,
            size_bytes=older.stat().st_size,
            timestamp=datetime(2020, 1, 1, 0, 0, 0),
            phash="hash",
        ),
        deduplicator.FileEntry(
            path=newer,
            size_bytes=newer.stat().st_size,
            timestamp=datetime(2021, 1, 1, 0, 0, 0),
            phash="hash",
        ),
    ]

    removed: list[str] = []

    def fake_send2trash(path: str) -> None:
        removed.append(path)

    monkeypatch.setattr(deduplicator, "send2trash", fake_send2trash)

    summary = deduplicator.remove_duplicates(
        {"hash": entries},
        destination=str(tmp_path),
        dry_run=False,
        confirm_delete=True,
    )

    assert summary.files_removed == 1
    assert str(older) in removed
    assert str(newer) not in removed


def test_find_duplicates_groups_by_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ["a.jpg", "b.jpg", "c.jpg"]:
        (tmp_path / name).write_text("x", encoding="utf-8")

    monkeypatch.setattr(deduplicator, "_hash_image", lambda path: "same")

    groups = deduplicator.find_duplicates(str(tmp_path))
    assert "same" in groups
    assert len(groups["same"]) == 3
