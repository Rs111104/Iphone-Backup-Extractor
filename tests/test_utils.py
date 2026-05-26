from datetime import datetime

import piexif
from PIL import Image

from ibackupx.utils import exif_datetime, human_bytes


def test_exif_datetime_reads_jpeg(tmp_path):
    img_path = tmp_path / "img.jpg"
    img = Image.new("RGB", (10, 10), color="red")
    img.save(img_path)
    exif_dict = {"Exif": {piexif.ExifIFD.DateTimeOriginal: "2020:01:02 03:04:05"}}
    exif_bytes = piexif.dump(exif_dict)
    img.save(img_path, exif=exif_bytes)
    dt = exif_datetime(img_path)
    assert isinstance(dt, datetime)


def test_human_bytes_formats():
    assert human_bytes(1024) == "1.0 KB"
    assert human_bytes(1024 * 1024) == "1.0 MB"
