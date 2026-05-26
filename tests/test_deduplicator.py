from pathlib import Path
from datetime import datetime

import piexif
from PIL import Image

from ibackupx import deduplicator


def test_exif_datetime_none_for_missing(tmp_path):
    missing = tmp_path / "nope.jpg"
    assert deduplicator._exif_datetime(missing) is None


def test_exif_datetime_reads_jpeg(tmp_path):
    img_path = tmp_path / "img.jpg"
    img = Image.new('RGB', (10, 10), color='red')
    img.save(img_path)
    # insert EXIF DateTimeOriginal
    exif_dict = {"Exif": {piexif.ExifIFD.DateTimeOriginal: "2020:01:02 03:04:05"}}
    exif_bytes = piexif.dump(exif_dict)
    img.save(img_path, exif=exif_bytes)
    dt = deduplicator._exif_datetime(img_path)
    assert isinstance(dt, datetime)
