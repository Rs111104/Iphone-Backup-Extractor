# iBackupX

Extract photos and videos from local iTunes/Finder iPhone backups, organize by date, remove duplicates, and repair corrupted images.

## Installation

```bash
git clone https://github.com/Rs111104/Iphone-Backup-Extractor.git
cd Iphone-Backup-Extractor
pip install -r requirements.txt
```

## Configuration

Copy the template and edit your local config:

```bash
copy config.example.json config.json
```

```json
{
  "backup_path": "",
  "destination": "",
  "organize_by_date": true,
  "skip_existing": true
}
```

Leave blank to use platform defaults (auto-detected on Windows and macOS).

- **backup_path**: Path to the iPhone backup. If empty, the tool uses the platform default.
- **destination**: Output folder for extracted files.
- **organize_by_date**: Store files in `YYYY/MM` folders.
- **skip_existing**: Skip files that already exist at the destination.

Passphrases are never stored in config files. Use `--passphrase` to enter one when needed.

## Usage

```bash
python main.py
```

### Command-line options

```bash
python main.py --extract
python main.py --duplicates
python main.py --repair
python main.py --all
python main.py --status

python main.py --backup "C:\\path\\to\\iPhone\\Backup" --dest "D:\\ExtractedPhotos"
python main.py --passphrase
python main.py --dry-run --all
```

### What each command does

- **Extract**: Reads `Manifest.db`, maps hashed files, and copies photos/videos to the destination.
- **Duplicates**: Uses perceptual hashes to find duplicate images and moves duplicates to trash after confirmation.
- **Repair**: Attempts to repair corrupted images and quarantines failures.
- **Status**: Shows device metadata, backup date, encryption status, and counts.

## Logs and reports

- `ibackupx.log`: Main application log in the destination folder.
- `extraction.log`: List of extracted files.
- `duplicates_report.txt`: Summary of removed duplicates.
- `repair_report.txt`: Summary of repairs and quarantined files.

## Notes

- Encrypted backups require the same passphrase used in iTunes/Finder.
- iCloud backups are not supported.
