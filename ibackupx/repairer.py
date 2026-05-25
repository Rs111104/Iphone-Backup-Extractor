"""Corrupted file repair engine."""

from __future__ import annotations

import io
import logging
import os
import pathlib
import shutil
from dataclasses import dataclass
from typing import Iterable

import piexif
from pillow_heif import register_heif_opener
from PIL import Image, UnidentifiedImageError
from tqdm import tqdm

from ibackupx import ExtractionError

logger = logging.getLogger(__name__)

register_heif_opener()

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".heic", ".png", ".gif"}


@dataclass
class RepairSummary:
    """Summary of repair results."""

    total_checked: int
    repaired: int
    quarantined: int
    unchanged: int


def _iter_images(destination: pathlib.Path) -> Iterable[pathlib.Path]:
    """Yield all supported image files under a destination folder."""
    for root, _, files in os.walk(destination):
        for name in files:
            if pathlib.Path(name).suffix.lower() in IMAGE_EXTENSIONS:
                yield pathlib.Path(root) / name


def _try_open(path: pathlib.Path) -> bool:
    """Return True if a file opens and verifies in Pillow."""
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, UnidentifiedImageError, ValueError):
        return False


def _resave_image(path: pathlib.Path, *, dry_run: bool) -> bool:
    """Attempt to resave an image without metadata."""
    try:
        with Image.open(path) as image:
            if dry_run:
                buffer = io.BytesIO()
                image.save(buffer, format=image.format)
                return True
            temp_path = path.with_suffix(path.suffix + ".tmp")
            image.save(temp_path, format=image.format)
        shutil.move(str(temp_path), str(path))
        return True
    except (OSError, UnidentifiedImageError, ValueError):
        return False


def _rewrite_exif(path: pathlib.Path, *, dry_run: bool) -> bool:
    """Attempt to rewrite EXIF data cleanly."""
    try:
        exif_bytes = piexif.dump({})
        with Image.open(path) as image:
            if dry_run:
                buffer = io.BytesIO()
                image.save(buffer, format=image.format, exif=exif_bytes)
                return True
            temp_path = path.with_suffix(path.suffix + ".tmp")
            image.save(temp_path, format=image.format, exif=exif_bytes)
        shutil.move(str(temp_path), str(path))
        return True
    except (OSError, UnidentifiedImageError, ValueError, piexif.InvalidImageDataError):
        return False


def _reencode_jpeg(path: pathlib.Path, *, dry_run: bool) -> bool:
    """Attempt to re-encode the image as JPEG."""
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            if dry_run:
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=95)
                return True
            temp_path = path.with_suffix(path.suffix + ".tmp")
            image.save(temp_path, format="JPEG", quality=95)
        shutil.move(str(temp_path), str(path))
        return True
    except (OSError, UnidentifiedImageError, ValueError):
        return False


def _move_to_quarantine(path: pathlib.Path, *, quarantine_root: pathlib.Path, dry_run: bool) -> None:
    """Move an unrecoverable file into the quarantine folder."""
    target = quarantine_root / path.name
    counter = 1
    while target.exists():
        target = quarantine_root / f"{path.stem}_{counter}{path.suffix}"
        counter += 1
    if dry_run:
        return
    quarantine_root.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(path), str(target))
    except OSError as exc:
        raise ExtractionError(f"Failed to move {path} to quarantine") from exc


def repair_files(destination: str, *, dry_run: bool) -> RepairSummary:
    """Attempt to repair corrupted images in the destination folder."""

    destination_path = pathlib.Path(destination)
    if not destination_path.exists():
        raise ExtractionError(f"Destination does not exist: {destination}")
    quarantine_root = destination_path / "quarantine"

    files = list(_iter_images(destination_path))
    total_checked = len(files)
    repaired = 0
    quarantined = 0
    unchanged = 0
    report_lines = []

    for path in tqdm(files, desc="Repairing", unit="file"):
        if _try_open(path):
            unchanged += 1
            continue

        repaired_this = False
        if _resave_image(path, dry_run=dry_run):
            repaired += 1
            repaired_this = True
            report_lines.append(f"REPAIRED: {path}")
        elif _rewrite_exif(path, dry_run=dry_run):
            repaired += 1
            repaired_this = True
            report_lines.append(f"REPAIRED: {path}")
        elif _reencode_jpeg(path, dry_run=dry_run):
            repaired += 1
            repaired_this = True
            report_lines.append(f"REPAIRED: {path}")
        else:
            quarantined += 1
            report_lines.append(f"QUARANTINED: {path}")
            _move_to_quarantine(path, quarantine_root=quarantine_root, dry_run=dry_run)

        if not repaired_this and not dry_run:
            logger.warning("Failed to repair %s", path)

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
