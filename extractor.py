"""Photo and video extraction engine."""

from __future__ import annotations

import logging
import pathlib
import plistlib
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence

from iphone_backup_decrypt import EncryptedBackup
from pillow_heif import register_heif_opener
from PIL import Image, UnidentifiedImageError
from rich.progress import (BarColumn, MofNCompleteColumn, Progress, TextColumn,
                           TimeRemainingColumn)

from ibackupx import ExtractionError
from ibackupx.config import Config
from ibackupx.inspector import is_encrypted_backup

logger = logging.getLogger(__name__)

register_heif_opener()

MEDIA_EXTENSIONS = [".jpg", ".jpeg", ".heic", ".png", ".gif", ".mov", ".mp4", ".aae"]


@dataclass
class ExtractionSummary:
    """Summary of extraction results."""

    total_found: int
    total_extracted: int
    total_skipped: int
    total_failed: int


def _extract_last_modified(file_blob: Optional[bytes]) -> Optional[int]:
    """Extract last-modified timestamp from a Manifest.db file blob."""
    if not file_blob:
        return None
    try:
        plist_data = plistlib.loads(file_blob)
    except (plistlib.InvalidFileException, ValueError, TypeError):
        return None
    return plist_data.get("LastModified") or plist_data.get("lastModified")


def _parse_exif_datetime(value: str) -> Optional[datetime]:
    """Parse EXIF date strings into a datetime instance."""
    try:
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _exif_datetime(path: pathlib.Path) -> Optional[datetime]:
    """Return the EXIF capture date if available."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            date_original = exif.get(36867)
            date_general = exif.get(306)
            date_primary = date_original or date_general
            if date_primary:
                return _parse_exif_datetime(str(date_primary))
    except (OSError, UnidentifiedImageError, ValueError):
        return None
    return None


def _normalise_timestamp(timestamp: Optional[int]) -> Optional[int]:
    """Normalize timestamps expressed in seconds or milliseconds."""
    if timestamp is None:
        return None
    if timestamp > 10**12:
        return int(timestamp / 1000)
    return int(timestamp)


def _destination_for_file(
    source_path: Optional[pathlib.Path],
    *,
    destination_root: pathlib.Path,
    organize_by_date: bool,
    last_modified: Optional[int],
    filename_override: Optional[str] = None,
) -> pathlib.Path:
    """Resolve the destination path for a file based on EXIF or timestamps."""
    filename = filename_override or (source_path.name if source_path else "unknown")
    suffix = pathlib.Path(filename).suffix
    if not suffix:
        base_name = source_path.name if source_path else filename
        filename = f"{base_name}.bin"
        logger.warning("Missing file extension for %s; writing as %s", base_name, filename)

    if not organize_by_date:
        return destination_root / filename

    if source_path:
        exif_dt = _exif_datetime(source_path)
        if exif_dt:
            return destination_root / f"{exif_dt.year:04d}" / f"{exif_dt.month:02d}" / filename

    normalised = _normalise_timestamp(last_modified)
    if normalised:
        fallback_dt = datetime.fromtimestamp(normalised)
        return destination_root / f"{fallback_dt.year:04d}" / f"{fallback_dt.month:02d}" / filename

    logger.warning("Missing EXIF and manifest timestamps for %s; using undated/", source_path)
    return destination_root / "undated" / filename


def _query_manifest(
    conn: sqlite3.Connection,
    *,
    extensions: Sequence[str],
) -> list[sqlite3.Row]:
    """Query Manifest.db for media file entries."""
    conn.row_factory = sqlite3.Row
    ext_sql = " OR ".join("relativePath LIKE ?" for _ in extensions)
    params = [f"%{ext}" for ext in extensions]
    sql = (
        "SELECT fileID, domain, relativePath, file "
        "FROM Files WHERE flags=1 AND (domain LIKE ? OR (" + ext_sql + "))"
    )
    return conn.execute(sql, ["CameraRollDomain%", *params]).fetchall()


def _source_path(backup_path: str, file_id: str) -> pathlib.Path:
    """Build the on-disk path for a hashed backup file."""
    return pathlib.Path(backup_path) / file_id[:2] / file_id


def extract_media_files(
    config: Config,
    *,
    passphrase: Optional[str],
    dry_run: bool,
) -> ExtractionSummary:
    """Extract media files from a backup into the configured destination."""

    backup_path = config.backup_path
    destination_root = pathlib.Path(config.destination)

    encrypted = is_encrypted_backup(backup_path)
    if encrypted and not passphrase:
        raise ExtractionError("Encrypted backup requires a passphrase.")
    if passphrase is not None and not passphrase:
        raise ExtractionError("Empty passphrase is not allowed.")

    rows: list[sqlite3.Row]
    if encrypted:
        backup = EncryptedBackup(backup_directory=backup_path, passphrase=passphrase)
        with backup.manifest_db_cursor() as cur:
            rows = _query_manifest(cur.connection, extensions=MEDIA_EXTENSIONS)
    else:
        manifest_db = pathlib.Path(backup_path) / "Manifest.db"
        try:
            with sqlite3.connect(str(manifest_db)) as conn:
                rows = _query_manifest(conn, extensions=MEDIA_EXTENSIONS)
        except sqlite3.Error as exc:
            raise ExtractionError("Unable to read Manifest.db") from exc

    total_found = len(rows)
    total_extracted = 0
    total_skipped = 0
    total_failed = 0

    extraction_log = None
    if not dry_run:
        try:
            destination_root.mkdir(parents=True, exist_ok=True)
            extraction_log = (destination_root / "extraction.log").open("a", encoding="utf-8")
        except OSError as exc:
            raise ExtractionError("Failed to prepare destination or extraction log") from exc

    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
    )

    with progress:
        task_id = progress.add_task("Extracting", total=total_found)
        for row in rows:
            file_id = row["fileID"]
            relative_path = row["relativePath"]
            domain = row["domain"]
            last_modified = _extract_last_modified(row["file"])
            filename = pathlib.Path(relative_path).name
            progress.update(task_id, description=filename)

            try:
                if encrypted:
                    if dry_run:
                        destination_path = _destination_for_file(
                            None,
                            destination_root=destination_root,
                            organize_by_date=config.organize_by_date,
                            last_modified=last_modified,
                            filename_override=filename,
                        )
                        if config.skip_existing and destination_path.exists():
                            total_skipped += 1
                        else:
                            total_extracted += 1
                    else:
                        with tempfile.TemporaryDirectory() as temp_dir:
                            temp_path = pathlib.Path(temp_dir) / filename
                            backup.extract_file(
                                relative_path=relative_path,
                                domain_like=domain,
                                output_filename=str(temp_path),
                            )
                            destination_path = _destination_for_file(
                                temp_path,
                                destination_root=destination_root,
                                organize_by_date=config.organize_by_date,
                                last_modified=last_modified,
                            )
                            if config.skip_existing and destination_path.exists():
                                total_skipped += 1
                            else:
                                destination_path.parent.mkdir(parents=True, exist_ok=True)
                                shutil.move(str(temp_path), str(destination_path))
                                total_extracted += 1
                                if extraction_log:
                                    extraction_log.write(f"{destination_path}\n")
                else:
                    source_path = _source_path(backup_path, file_id)
                    destination_path = _destination_for_file(
                        source_path,
                        destination_root=destination_root,
                        organize_by_date=config.organize_by_date,
                        last_modified=last_modified,
                    )
                    if config.skip_existing and destination_path.exists():
                        total_skipped += 1
                    elif dry_run:
                        total_extracted += 1
                    else:
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_path, destination_path)
                        total_extracted += 1
                        if extraction_log:
                            extraction_log.write(f"{destination_path}\n")
            except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
                total_failed += 1
                logger.error("Failed to extract %s: %s", relative_path, exc)

            progress.advance(task_id)

    if extraction_log:
        extraction_log.close()

    return ExtractionSummary(
        total_found=total_found,
        total_extracted=total_extracted,
        total_skipped=total_skipped,
        total_failed=total_failed,
    )
