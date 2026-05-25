"""Backup status inspection and reporting."""

from __future__ import annotations

import logging
import os
import pathlib
import plistlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from iphone_backup_decrypt import EncryptedBackup
from rich.panel import Panel
from rich.table import Table

from ibackupx import BackupError

logger = logging.getLogger(__name__)

MEDIA_EXTENSIONS = [".jpg", ".jpeg", ".heic", ".png", ".gif", ".mov", ".mp4", ".aae"]


@dataclass
class BackupInfo:
    """Metadata describing an iPhone backup."""

    device_name: str
    device_model: str
    ios_version: str
    backup_date: Optional[datetime]
    encrypted: bool
    total_files: Optional[int]
    media_files: Optional[int]
    backup_size_bytes: int


def _human_bytes(value: int) -> str:
    """Convert bytes to a human-readable string."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def _read_plist(path: pathlib.Path) -> dict:
    """Read a plist file if it exists, returning an empty dict on failure."""
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            return plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        logger.warning("Failed to read plist %s: %s", path, exc)
        return {}


def is_encrypted_backup(backup_path: str) -> bool:
    """Return True if the backup is encrypted."""

    manifest_plist = pathlib.Path(backup_path) / "Manifest.plist"
    plist_data = _read_plist(manifest_plist)
    return bool(plist_data.get("WasPasscodeSet"))


def _backup_size_bytes(backup_path: str) -> int:
    """Compute the total size of files in the backup folder."""
    total = 0
    for root, _, files in os.walk(backup_path):
        for name in files:
            try:
                total += (pathlib.Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _count_manifest_files(
    conn: sqlite3.Connection,
    *,
    media_extensions: Sequence[str],
) -> tuple[int, int]:
    """Count all files and media files in the Manifest database."""
    conn.row_factory = sqlite3.Row
    total_row = conn.execute("SELECT COUNT(*) AS total FROM Files WHERE flags=1").fetchone()
    total_files = int(total_row["total"])

    extension_sql = " OR ".join("relativePath LIKE ?" for _ in media_extensions)
    params = [f"%{ext}" for ext in media_extensions]
    media_row = conn.execute(
        f"SELECT COUNT(*) AS media FROM Files WHERE flags=1 AND domain LIKE ? AND ({extension_sql})",
        ["CameraRollDomain%", *params],
    ).fetchone()
    media_files = int(media_row["media"])
    return total_files, media_files


def inspect_backup(backup_path: str, *, passphrase: Optional[str]) -> BackupInfo:
    """Inspect backup metadata and return a summary."""

    backup_root = pathlib.Path(backup_path)
    if not backup_root.exists():
        raise BackupError(f"Backup path does not exist: {backup_path}")

    status_plist = _read_plist(backup_root / "Status.plist")
    info_plist = _read_plist(backup_root / "Info.plist")

    device_name = info_plist.get("Device Name") or info_plist.get("DeviceName") or "Unknown"
    device_model = info_plist.get("Product Type") or info_plist.get("ProductType") or "Unknown"
    ios_version = info_plist.get("Product Version") or info_plist.get("ProductVersion") or "Unknown"
    status_date = status_plist.get("Date")
    backup_date = status_date if isinstance(status_date, datetime) else None
    encrypted = is_encrypted_backup(backup_path)

    total_files: Optional[int] = None
    media_files: Optional[int] = None

    if encrypted:
        if passphrase:
            backup = EncryptedBackup(backup_directory=backup_path, passphrase=passphrase)
            with backup.manifest_db_cursor() as cur:
                total_files, media_files = _count_manifest_files(cur.connection, media_extensions=MEDIA_EXTENSIONS)
    else:
        manifest_db = backup_root / "Manifest.db"
        try:
            with sqlite3.connect(str(manifest_db)) as conn:
                total_files, media_files = _count_manifest_files(conn, media_extensions=MEDIA_EXTENSIONS)
        except sqlite3.Error as exc:
            raise BackupError("Unable to read Manifest.db") from exc

    backup_size = _backup_size_bytes(backup_path)

    return BackupInfo(
        device_name=device_name,
        device_model=device_model,
        ios_version=ios_version,
        backup_date=backup_date,
        encrypted=encrypted,
        total_files=total_files,
        media_files=media_files,
        backup_size_bytes=backup_size,
    )


def render_backup_info(info: BackupInfo) -> Panel:
    """Render backup info as a Rich panel."""

    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Device", f"{info.device_name} ({info.device_model})")
    table.add_row("iOS", info.ios_version)
    table.add_row("Backup date", info.backup_date.isoformat() if info.backup_date else "Unknown")
    table.add_row("Encrypted", "Yes" if info.encrypted else "No")
    table.add_row("Total files", str(info.total_files) if info.total_files is not None else "Locked")
    table.add_row("Photos/videos", str(info.media_files) if info.media_files is not None else "Locked")
    table.add_row("Backup size", _human_bytes(info.backup_size_bytes))
    return Panel(table, title="Backup status", expand=False)
