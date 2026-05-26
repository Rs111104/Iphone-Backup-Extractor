"""Photo and video extraction engine."""

import logging
import pathlib
import plistlib
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime

from iphone_backup_decrypt import EncryptedBackup
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn

from ibackupx import ExtractionError
from ibackupx.config import Config
from ibackupx.constants import MEDIA_EXTENSIONS
from ibackupx.inspector import is_encrypted_backup
from ibackupx.utils import exif_datetime, safe_copy_file, safe_replace_file

logger = logging.getLogger(__name__)


@dataclass
class ExtractionSummary:
    """Summary of extraction results."""

    total_found: int
    total_extracted: int
    total_skipped: int
    total_failed: int


def _extract_last_modified(file_blob: bytes | None) -> int | None:
    """Extract last-modified timestamp from a Manifest.db file blob."""
    if not file_blob:
        return None
    try:
        plist_data = plistlib.loads(file_blob)
    except (plistlib.InvalidFileException, ValueError, TypeError):
        return None
    return plist_data.get("LastModified") or plist_data.get("lastModified")


def _normalise_timestamp(timestamp: int | None) -> int | None:
    if timestamp is None:
        return None
    if timestamp > 10**12:
        return int(timestamp / 1000)
    return int(timestamp)


def _destination_for_file(
    source_path: pathlib.Path | None,
    *,
    destination_root: pathlib.Path,
    organize_by_date: bool,
    last_modified: int | None,
    filename_override: str | None = None,
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
        exif_dt = exif_datetime(source_path)
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
    extensions: tuple[str, ...] | set[str] | list[str],
) -> list[sqlite3.Row]:
    """Query Manifest.db for media file entries."""
    conn.row_factory = sqlite3.Row
    ext_sql = " OR ".join("relativePath LIKE ?" for _ in extensions)
    params = [f"%{ext}" for ext in extensions]
    sql = (
        "SELECT fileID, domain, relativePath, file "
        "FROM Files WHERE flags=1 AND domain LIKE 'CameraRollDomain%' AND (" + ext_sql + ")"
    )
    return conn.execute(sql, params).fetchall()


def _source_path(backup_path: str, file_id: str) -> pathlib.Path:
    return pathlib.Path(backup_path) / file_id[:2] / file_id


def extract_media_files(
    config: Config,
    *,
    passphrase: str | None,
    dry_run: bool,
) -> ExtractionSummary:
    """Extract media files from a backup into the configured destination."""

    backup_path = config.backup_path
    destination_root = pathlib.Path(config.destination)

    encrypted = is_encrypted_backup(backup_path)
    if encrypted and not passphrase:
        raise ExtractionError("Encrypted backup requires a passphrase.")

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

    if not rows:
        logger.warning(
            "No media files found in Manifest.db. If you expected photos, verify the backup at %s "
            "is complete and not from iOS 8 or earlier.",
            backup_path,
        )

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
                            try:
                                if destination_path.stat().st_size > 0:
                                    logger.debug("Skipping existing file (non-zero size): %s", destination_path)
                                    total_skipped += 1
                                    continue
                                else:
                                    # zero-byte file: remove and treat as missing (do not delete in dry-run)
                                    logger.debug("Found zero-byte file, will re-extract: %s", destination_path)
                                    if not dry_run:
                                        try:
                                            destination_path.unlink()
                                        except OSError:
                                            logger.warning("Failed to remove zero-byte file: %s", destination_path)
                            except OSError:
                                # Couldn't stat the file, attempt extraction
                                pass
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
                                try:
                                    if destination_path.stat().st_size > 0:
                                        logger.debug("Skipping existing file (non-zero size): %s", destination_path)
                                        total_skipped += 1
                                        continue
                                    else:
                                        # zero-byte file: remove and proceed to move
                                        if not dry_run:
                                            try:
                                                destination_path.unlink()
                                            except OSError:
                                                logger.warning("Failed to remove zero-byte file: %s", destination_path)
                                except OSError:
                                    pass
                            safe_replace_file(temp_path, destination_path, dry_run=dry_run)
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
                        try:
                            if destination_path.stat().st_size > 0:
                                logger.debug("Skipping existing file (non-zero size): %s", destination_path)
                                total_skipped += 1
                                continue
                            else:
                                logger.debug("Found zero-byte file, will re-extract: %s", destination_path)
                                try:
                                    destination_path.unlink()
                                except OSError:
                                    logger.warning("Failed to remove zero-byte file: %s", destination_path)
                        except OSError:
                            pass
                    if dry_run:
                        total_extracted += 1
                    else:
                        safe_copy_file(source_path, destination_path, dry_run=dry_run)
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
