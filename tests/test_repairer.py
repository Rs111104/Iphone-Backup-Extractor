from pathlib import Path

from ibackupx import repairer


def test_iter_images_skips_quarantine(tmp_path):
    dest = tmp_path / "out"
    (dest / "quarantine").mkdir(parents=True)
    (dest / "quarantine" / "bad.jpg").write_text("x")
    (dest / "good").mkdir()
    (dest / "good" / "ok.jpg").write_text("x")
    found = list(repairer._iter_images(dest))
    assert all("quarantine" not in str(p) for p in found)


def test_format_from_suffix():
    assert repairer._FORMAT_FROM_SUFFIX.get('.jpg') == 'JPEG'
    assert repairer._FORMAT_FROM_SUFFIX.get('.jpeg') == 'JPEG'
    assert repairer._FORMAT_FROM_SUFFIX.get('.heic') == 'HEIF'
