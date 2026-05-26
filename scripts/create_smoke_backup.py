import pathlib
import sqlite3
import plistlib
import json

root = pathlib.Path("smoke_backup")
root.mkdir(exist_ok=True)
sub = root / "abcd"
sub.mkdir(parents=True, exist_ok=True)
# Create simple Manifest.db with Files table
db = sub / "Manifest.db"
conn = sqlite3.connect(str(db))
conn.execute("CREATE TABLE IF NOT EXISTS Files (fileID TEXT, domain TEXT, relativePath TEXT, file BLOB, flags INTEGER)")
conn.commit()
conn.close()
# Write Manifest.plist with IsEncrypted False
plist = sub / "Manifest.plist"
with plist.open("wb") as f:
    plistlib.dump({"IsEncrypted": False}, f)
# Write a smoke config pointing to the backup parent
cfg = {
    "backup_path": str(root),
    "destination": str(pathlib.Path("smoke_out")),
    "organize_by_date": True,
    "skip_existing": True,
}
with open("config.smoke.json", "w", encoding="utf-8") as f:
    json.dump(cfg, f)
print("Smoke backup and config created: smoke_backup/abcd, config.smoke.json")
