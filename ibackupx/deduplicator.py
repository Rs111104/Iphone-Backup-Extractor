"""Duplicate detection and removal."""

import logging
import os
import pathlib
from dataclasses import dataclass
from datetime import datetime

import imagehash
from pillow_heif import register_heif_opener
from PIL import Image, UnidentifiedImageError
from rich.table import Table
from send2trash import send2trash

from ibackupx import ExtractionError
from ibackupx.constants import IMAGE_EXTENSIONS
from ibackupx.utils import exif_datetime

logger = logging.getLogger(__name__)

register_heif_opener()


@dataclass
class FileEntry:
    """Represents a candidate file for de-duplication."""

    path: pathlib.Path
    size_bytes: int
    timestamp: datetime
    phash: str


@dataclass
class DuplicateSummary:
    """Summary of duplicate detection results."""

    groups_found: int
    files_removed: int
    space_freed_bytes: int


def _exif_datetime(path: pathlib.Path) -> datetime | None:
    return exif_datetime(path)


def _file_timestamp(path: pathlib.Path) -> datetime:
    """Return the best available timestamp for a file."""
    exif_dt = _exif_datetime(path)
    if exif_dt:
        return exif_dt
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError as exc:
        raise ExtractionError(f"Failed to read timestamp for {path}") from exc


def _hash_image(path: pathlib.Path, *, hash_size: int) -> str | None:
    try:
        with Image.open(path) as image:
            return str(imagehash.phash(image, hash_size=hash_size))
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        logger.warning("Failed to hash %s: %s", path, exc)
        return None


def _iter_image_files(destination: pathlib.Path) -> list[pathlib.Path]:
    matches: list[pathlib.Path] = []
    for root, _, files in os.walk(destination):
        for name in files:
            if pathlib.Path(name).suffix.lower() in IMAGE_EXTENSIONS:
                matches.append(pathlib.Path(root) / name)
    return matches


def build_duplicates_table(groups: dict[str, list[FileEntry]]) -> Table:
    """Build a Rich table for duplicate groups."""

    table = Table(title="Duplicate groups")
    table.add_column("Hash", style="bold")
    table.add_column("File")
    table.add_column("Path")
    table.add_column("Size")
    table.add_column("Date")

    for phash, entries in groups.items():
        for entry in entries:
            table.add_row(
                phash,
                entry.path.name,
                str(entry.path.parent),
                f"{entry.size_bytes / 1024:.1f} KB",
                entry.timestamp.isoformat(timespec="seconds"),
            )
    return table


def find_duplicates(destination: str, *, hash_size: int) -> dict[str, list[FileEntry]]:
    """Find duplicate files grouped by perceptual hash."""

    destination_path = pathlib.Path(destination)
    if not destination_path.exists():
        raise ExtractionError(f"Destination does not exist: {destination}")
    groups: dict[str, list[FileEntry]] = {}

    for path in _iter_image_files(destination_path):
        phash = _hash_image(path, hash_size=hash_size)
        if not phash:
            continue
        try:
            entry = FileEntry(
                path=path,
                size_bytes=path.stat().st_size,
                timestamp=_file_timestamp(path),
                phash=phash,
            )
        except (OSError, ExtractionError) as exc:
            logger.warning("Failed to read metadata for %s: %s", path, exc)
            continue
        groups.setdefault(phash, []).append(entry)

    return {phash: entries for phash, entries in groups.items() if len(entries) > 1}


def remove_duplicates(
    groups: dict[str, list[FileEntry]],
    *,
    destination: str,
    dry_run: bool,
    confirm_delete: bool,
) -> DuplicateSummary:
    """Remove duplicates and return a summary."""

    if not confirm_delete:
        return DuplicateSummary(groups_found=len(groups), files_removed=0, space_freed_bytes=0)

    removed = 0
    freed = 0
    report_lines: list[str] = []

    for entries in groups.values():
        entries_sorted = sorted(entries, key=lambda item: item.timestamp, reverse=True)
        keep = entries_sorted[0]
        report_lines.append(f"KEEP: {keep.path}")
        for duplicate in entries_sorted[1:]:
            report_lines.append(f"REMOVE: {duplicate.path}")
            if dry_run:
                removed += 1
                freed += duplicate.size_bytes
                continue
            try:
                send2trash(str(duplicate.path))
                removed += 1
                freed += duplicate.size_bytes
            except OSError as exc:
                logger.error("Failed to remove %s: %s", duplicate.path, exc)

    if not dry_run and report_lines:
        report_path = pathlib.Path(destination) / "duplicates_report.txt"
        try:
            report_path.write_text("\n".join(report_lines), encoding="utf-8")
        except OSError as exc:
            raise ExtractionError("Failed to write duplicates report") from exc

    return DuplicateSummary(groups_found=len(groups), files_removed=removed, space_freed_bytes=freed)
