"""Click-based command line interface for iBackupX."""

import logging
import os

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ibackupx import BackupError, ConfigError, ExtractionError, __version__
from ibackupx.config import apply_overrides, load_config
from ibackupx.deduplicator import build_duplicates_table, find_duplicates, remove_duplicates
from ibackupx.extractor import ExtractionSummary, extract_media_files
from ibackupx.inspector import find_backup_dirs, inspect_backup, is_encrypted_backup, render_backup_info
from ibackupx.logger import setup_logging
from ibackupx.repairer import RepairSummary, repair_files

logger = logging.getLogger(__name__)


def _summary_table(title: str, data: dict) -> Table:
    """Build a Rich table from a mapping of summary values."""
    table = Table(title=title)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    for key, value in data.items():
        table.add_row(str(key), str(value))
    return table


def _render_extraction_summary(summary: ExtractionSummary) -> Table:
    """Render an extraction summary table."""
    return _summary_table(
        "Extraction summary",
        {
            "Total found": summary.total_found,
            "Extracted": summary.total_extracted,
            "Skipped": summary.total_skipped,
            "Failed": summary.total_failed,
        },
    )


def _render_repair_summary(summary: RepairSummary) -> Table:
    """Render a repair summary table."""
    return _summary_table(
        "Repair summary",
        {
            "Checked": summary.total_checked,
            "Repaired": summary.repaired,
            "Quarantined": summary.quarantined,
            "Unchanged": summary.unchanged,
        },
    )


def _menu_choice() -> str:
    """Prompt for a menu selection."""
    return click.prompt("Choose an option", type=click.Choice(["1", "2", "3", "4", "5"]), default="5")


def _prompt_passphrase() -> str | None:
    """Prompt the user for a backup passphrase."""
    value = click.prompt("Backup passphrase", hide_input=True, default="")
    value = value.strip()
    return value or None


@click.version_option(version="1.0.0", prog_name="iBackupX")
@click.command()
@click.option("--extract", "do_extract", is_flag=True, help="Extract photos and videos")
@click.option("--duplicates", "do_duplicates", is_flag=True, help="Find and remove duplicates")
@click.option("--repair", "do_repair", is_flag=True, help="Repair corrupted images")
@click.option("--all", "do_all", is_flag=True, help="Run extract, duplicates, and repair")
@click.option("--status", "show_status", is_flag=True, help="Show backup status only")
@click.option("--backup", "backup_path", help="Override backup_path from config.json")
@click.option("--dest", "destination", help="Override destination from config.json")
@click.option("--hash-size", "hash_size", type=int, help="Override perceptual hash size")
@click.option("--passphrase", "prompt_passphrase", is_flag=True, help="Prompt for backup passphrase")
@click.option("--dry-run", is_flag=True, help="Simulate actions without writing")
@click.option("--config", "config_path", default="config.json", show_default=True, help="Config file path")
@click.option("--verbose", is_flag=True, help="Enable debug logging")
def main(
    do_extract: bool,
    do_duplicates: bool,
    do_repair: bool,
    do_all: bool,
    show_status: bool,
    backup_path: str | None,
    destination: str | None,
    hash_size: int | None,
    prompt_passphrase: bool,
    dry_run: bool,
    config_path: str,
    verbose: bool,
) -> None:
    """Run iBackupX from the command line."""

    console = Console()

    try:
        config = load_config(config_path)
        config = apply_overrides(
            config,
            {
                "backup_path": backup_path,
                "destination": destination,
                "hash_size": hash_size,
            },
        )
        config.backup_path = find_backup_dirs(config.backup_path)
    except (ConfigError, BackupError) as exc:
        raise click.ClickException(str(exc)) from exc

    setup_logging(config.destination, verbose=verbose, enable_file=not dry_run)

    encrypted = is_encrypted_backup(config.backup_path)
    # Passphrase via environment variable for automation
    passphrase = None
    env_pass = os.environ.get("IBACKUPX_PASSPHRASE")
    if env_pass:
        passphrase = env_pass
    elif prompt_passphrase:
        passphrase = _prompt_passphrase()

    if show_status:
        try:
            info = inspect_backup(config.backup_path, passphrase=passphrase)
        except (BackupError, ExtractionError) as exc:
            raise click.ClickException(str(exc)) from exc
        console.print(render_backup_info(info))
        return

    actions_selected = any([do_extract, do_duplicates, do_repair, do_all])

    if not actions_selected:
        console.print(Panel(f"iBackupX v{__version__}", style="bold green"))
        try:
            info = inspect_backup(config.backup_path, passphrase=passphrase)
        except (BackupError, ExtractionError) as exc:
            raise click.ClickException(str(exc)) from exc
        console.print(render_backup_info(info))
        console.print("[1] Extract  [2] Find Duplicates  [3] Repair  [4] All  [5] Exit")
        choice = _menu_choice()
        if choice == "1":
            do_extract = True
        elif choice == "2":
            do_duplicates = True
        elif choice == "3":
            do_repair = True
        elif choice == "4":
            do_all = True
        else:
            return

    if do_all:
        do_extract = True
        do_duplicates = True
        do_repair = True

    if encrypted and do_extract and not passphrase:
        passphrase = _prompt_passphrase()

    if do_extract:
        try:
            extraction_summary = extract_media_files(config, passphrase=passphrase, dry_run=dry_run)
        except (BackupError, ExtractionError) as exc:
            raise click.ClickException(str(exc)) from exc
        console.print(_render_extraction_summary(extraction_summary))

    if do_duplicates:
        try:
            groups = find_duplicates(config.destination, hash_size=config.hash_size)
        except ExtractionError as exc:
            raise click.ClickException(str(exc)) from exc

        if not groups:
            console.print(_summary_table("Duplicate summary", {"Groups found": 0, "Files removed": 0, "Space freed": "0 B"}))
        else:
            console.print(build_duplicates_table(groups))
            space_freed = sum(
                entry.size_bytes
                for entries in groups.values()
                for entry in sorted(entries, key=lambda item: item.timestamp, reverse=True)[1:]
            )
            remove_count = sum(len(entries) - 1 for entries in groups.values())
            console.print(f"Potential removal: {remove_count} files, {space_freed / 1024:.1f} KB")
            confirm_delete = click.confirm("Move duplicates to trash?", default=False)
            summary = remove_duplicates(
                groups,
                destination=config.destination,
                dry_run=dry_run,
                confirm_delete=confirm_delete,
            )
            console.print(
                _summary_table(
                    "Duplicate summary",
                    {
                        "Groups found": summary.groups_found,
                        "Files removed": summary.files_removed,
                        "Space freed": f"{summary.space_freed_bytes / 1024:.1f} KB",
                    },
                )
            )

    if do_repair:
        try:
            repair_summary = repair_files(config.destination, dry_run=dry_run)
        except ExtractionError as exc:
            raise click.ClickException(str(exc)) from exc
        console.print(_render_repair_summary(repair_summary))
