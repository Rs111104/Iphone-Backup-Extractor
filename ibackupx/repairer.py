"""Corrupted file repair engine."""

import io
import logging
import os
import pathlib
import shutil
from dataclasses import dataclass
from datetime import datetime

import piexif
from pillow_heif import register_heif_opener
from PIL import Image, UnidentifiedImageError
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn

from ibackupx import ExtractionError
from ibackupx.constants import IMAGE_EXTENSIONS
from ibackupx.utils import safe_replace_file

logger = logging.getLogger(__name__)

register_heif_opener()

_FORMAT_FROM_SUFFIX = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".gif": "GIF",
    ".heic": "HEIF",
    ".heif": "HEIF",
}


@dataclass
class RepairSummary:
    """Summary of repair results."""

    total_checked: int
    repaired: int
    quarantined: int
    unchanged: int


def _iter_images(destination: pathlib.Path) -> list[pathlib.Path]:
    quarantine_path = destination / "quarantine"
    matches: list[pathlib.Path] = []
    for root, dirs, files in os.walk(destination):
        dirs[:] = [d for d in dirs if pathlib.Path(root) / d != quarantine_path]
        for name in files:
            if pathlib.Path(name).suffix.lower() in IMAGE_EXTENSIONS:
                matches.append(pathlib.Path(root) / name)
    return matches


def _try_open(path: pathlib.Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, UnidentifiedImageError, ValueError):
        return False


def _strip_exif(path: pathlib.Path, *, dry_run: bool) -> bool:
    if path.suffix.lower() not in {".jpg", ".jpeg"}:
        return False
    try:
        if dry_run:
            piexif.load(str(path))
            return True
        temp_path = path.with_suffix(path.suffix + ".tmp")
        piexif.remove(str(path), str(temp_path))
        safe_replace_file(temp_path, path, dry_run=False)
        return True
    except (OSError, ValueError, piexif.InvalidImageDataError):
        return False


def _lossless_reencode(path: pathlib.Path, *, dry_run: bool) -> bool:
    suffix = path.suffix.lower()
    if suffix in {".heic", ".heif"}:
        return False
    fmt = _FORMAT_FROM_SUFFIX.get(suffix)
    if not fmt:
        return False
    try:
        with Image.open(path) as image:
            if dry_run:
                buffer = io.BytesIO()
                image.save(buffer, format=fmt)
                return True
            temp_path = path.with_suffix(path.suffix + ".tmp")
            image.save(temp_path, format=fmt)
        safe_replace_file(temp_path, path, dry_run=False)
        return True
    except (OSError, UnidentifiedImageError, ValueError):
        return False


def _lossy_reencode_jpeg(path: pathlib.Path, *, dry_run: bool) -> bool:
    if path.suffix.lower() not in {".jpg", ".jpeg"}:
        return False
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            if dry_run:
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=90)
                return True
            temp_path = path.with_suffix(path.suffix + ".tmp")
            image.save(temp_path, format="JPEG", quality=90)
        safe_replace_file(temp_path, path, dry_run=False)
        return True
    except (OSError, UnidentifiedImageError, ValueError):
        return False


def _move_to_quarantine(path: pathlib.Path, *, quarantine_root: pathlib.Path, dry_run: bool) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = quarantine_root / f"{path.stem}_{stamp}{path.suffix}"
    counter = 1
    while target.exists():
        target = quarantine_root / f"{path.stem}_{stamp}_{counter}{path.suffix}"
        counter += 1
    if dry_run:
        return
    quarantine_root.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(path), str(target))
        logger.info("Quarantined %s", target)
    except OSError as exc:
        raise ExtractionError(f"Failed to move {path} to quarantine") from exc


def repair_files(destination: str, *, dry_run: bool) -> RepairSummary:
    destination_path = pathlib.Path(destination)
    if not destination_path.exists():
        raise ExtractionError(f"Destination does not exist: {destination}")
    quarantine_root = destination_path / "quarantine"

    files = _iter_images(destination_path)
    total_checked = len(files)
    repaired = 0
    quarantined = 0
    unchanged = 0
    report_lines: list[str] = []

    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
    )

    with progress:
        task_id = progress.add_task("Repairing", total=total_checked)
        for path in files:
            progress.update(task_id, description=path.name)
            if _try_open(path):
                unchanged += 1
                progress.advance(task_id)
                continue

            repaired_this = False
            if _strip_exif(path, dry_run=dry_run):
                repaired += 1
                repaired_this = True
                report_lines.append(f"REPAIRED: {path}")
            elif _lossless_reencode(path, dry_run=dry_run):
                repaired += 1
                repaired_this = True
                report_lines.append(f"REPAIRED: {path}")
            elif _lossy_reencode_jpeg(path, dry_run=dry_run):
                repaired += 1
                repaired_this = True
                report_lines.append(f"REPAIRED: {path}")
            else:
                quarantined += 1
                report_lines.append(f"QUARANTINED: {path}")
                _move_to_quarantine(path, quarantine_root=quarantine_root, dry_run=dry_run)

            if not repaired_this and dry_run:
                logger.info("Would quarantine %s", path)

            progress.advance(task_id)

    if report_lines and not dry_run:
        report_path = destination_path / "repair_report.txt"
        try:
            report_path.write_text("\n".join(report_lines), encoding="utf-8")
        except OSError as exc:
            raise ExtractionError("Failed to write repair report") from exc

    return RepairSummary(
        total_checked=total_checked,
        repaired=repaired,
        quarantined=quarantined,
        unchanged=unchanged,
    )
