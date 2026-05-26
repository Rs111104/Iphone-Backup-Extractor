from ibackupx import repairer


def test_iter_images_skips_quarantine(tmp_path):
    dest = tmp_path / "out"
    (dest / "quarantine").mkdir(parents=True)
    (dest / "quarantine" / "bad.jpg").write_text("x", encoding="utf-8")
    (dest / "good").mkdir()
    (dest / "good" / "ok.jpg").write_text("x", encoding="utf-8")
    found = list(repairer._iter_images(dest))
    assert all("quarantine" not in str(p) for p in found)


def test_repair_png_does_not_create_jpeg(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    broken_png = dest / "broken.png"
    broken_png.write_bytes(b"not a real png")

    repairer.repair_files(str(dest), dry_run=False)

    quarantine = dest / "quarantine"
    if quarantine.exists():
        assert all(p.suffix.lower() != ".jpg" for p in quarantine.rglob("*") if p.is_file())
    assert not list(dest.glob("*.jpg"))
