from datetime import datetime

from ibackupx import deduplicator


def test_remove_duplicates_keeps_newest(tmp_path, monkeypatch):
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
