import os
import pathlib
import shutil
from datetime import datetime

import piexif


def exif_datetime(path: pathlib.Path) -> datetime | None:
    try:
        exif_data = piexif.load(str(path))
    except (OSError, ValueError, piexif.InvalidImageDataError):
        return None

    for ifd, tag in (("Exif", piexif.ExifIFD.DateTimeOriginal), ("0th", piexif.ImageIFD.DateTime)):
        raw = exif_data.get(ifd, {}).get(tag)
        if raw:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="ignore")
            try:
                return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
            except ValueError:
                return None
    return None


def human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def _backup_copy(path: pathlib.Path) -> pathlib.Path | None:
    if not path.exists():
        return None
    backup_path = path.with_name(path.name + ".bak")
    shutil.copy2(path, backup_path)
    return backup_path


def safe_copy_file(source: pathlib.Path, destination: pathlib.Path, *, dry_run: bool) -> None:
    """Copy a file with a crash-safe .bak guard.

    If destination exists, a .bak copy is created first and only removed after a
    successful copy completes.
    """
    if dry_run:
        return
    backup_path = _backup_copy(destination)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    except OSError:
        raise
    else:
        if backup_path and backup_path.exists():
            backup_path.unlink()


def safe_replace_file(source: pathlib.Path, destination: pathlib.Path, *, dry_run: bool) -> None:
    """Replace a file with a crash-safe .bak guard.

    If destination exists, a .bak copy is created first and only removed after a
    successful replace completes.
    """
    if dry_run:
        return
    backup_path = _backup_copy(destination)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(source, destination)
        except OSError:
            shutil.copy2(source, destination)
            if source.exists():
                source.unlink()
    except OSError:
        raise
    else:
        if backup_path and backup_path.exists():
            backup_path.unlink()
