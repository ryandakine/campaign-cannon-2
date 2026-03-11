#!/usr/bin/env python3
"""Backup and restore script for Campaign Cannon.

Creates timestamped .tar.gz archives of the SQLite database and campaigns directory.

Usage:
    python scripts/backup.py                     # Create backup
    python scripts/backup.py --restore latest     # Restore most recent backup
    python scripts/backup.py --restore <path>     # Restore specific archive
"""

import argparse
import glob
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "campaign_cannon.db"
CAMPAIGNS_DIR = PROJECT_ROOT / "campaigns"
BACKUPS_DIR = PROJECT_ROOT / "backups"


def checkpoint_wal(db_path: Path) -> None:
    """Force SQLite WAL checkpoint before backup for consistency."""
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        print(f"[backup] WAL checkpoint completed: {db_path}")
    except Exception as e:
        print(f"[backup] WAL checkpoint warning: {e}")


def create_backup(db_path: Path = DEFAULT_DB_PATH) -> Path:
    """Create a timestamped backup archive.

    Returns the path to the created archive.
    """
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_name = f"campaign_cannon_backup_{timestamp}.tar.gz"
    archive_path = BACKUPS_DIR / archive_name

    # Checkpoint WAL before copying
    checkpoint_wal(db_path)

    with tarfile.open(archive_path, "w:gz") as tar:
        # Backup database files
        if db_path.exists():
            tar.add(db_path, arcname=f"data/{db_path.name}")
            # Also backup WAL and SHM files if they exist
            for suffix in ["-wal", "-shm"]:
                wal_path = db_path.parent / f"{db_path.name}{suffix}"
                if wal_path.exists():
                    tar.add(wal_path, arcname=f"data/{wal_path.name}")
            print(f"[backup] Database backed up: {db_path}")
        else:
            print(f"[backup] No database found at {db_path}, skipping.")

        # Backup campaigns directory
        if CAMPAIGNS_DIR.exists() and any(CAMPAIGNS_DIR.iterdir()):
            tar.add(CAMPAIGNS_DIR, arcname="campaigns")
            print(f"[backup] Campaigns directory backed up: {CAMPAIGNS_DIR}")
        else:
            print("[backup] No campaigns directory or empty, skipping.")

    # Print summary
    size_bytes = archive_path.stat().st_size
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

    print(f"\n[backup] Archive created: {archive_path}")
    print(f"[backup] Size: {size_str}")
    return archive_path


def restore_backup(archive_path_or_latest: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Restore from a backup archive.

    Args:
        archive_path_or_latest: Path to .tar.gz archive, or "latest" for most recent.
        db_path: Target database path.
    """
    if archive_path_or_latest == "latest":
        archives = sorted(BACKUPS_DIR.glob("campaign_cannon_backup_*.tar.gz"))
        if not archives:
            print("[restore] No backup archives found in ./backups/")
            sys.exit(1)
        archive_path = archives[-1]
        print(f"[restore] Using latest backup: {archive_path.name}")
    else:
        archive_path = Path(archive_path_or_latest)

    if not archive_path.exists():
        print(f"[restore] Archive not found: {archive_path}")
        sys.exit(1)

    print(f"[restore] Restoring from: {archive_path}")

    # Safety: confirm before overwriting
    if db_path.exists() or (CAMPAIGNS_DIR.exists() and any(CAMPAIGNS_DIR.iterdir())):
        print("[restore] WARNING: This will overwrite existing data!")
        response = input("[restore] Continue? (yes/no): ").strip().lower()
        if response != "yes":
            print("[restore] Aborted.")
            return

    with tarfile.open(archive_path, "r:gz") as tar:
        # Security: check for path traversal
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in member.name:
                print(f"[restore] SECURITY: Skipping suspicious path: {member.name}")
                continue

        # Extract to project root
        tar.extractall(path=PROJECT_ROOT, filter="data")

    print(f"[restore] Restored database to: {db_path.parent}")
    print(f"[restore] Restored campaigns to: {CAMPAIGNS_DIR}")
    print("[restore] Done!")


def list_backups() -> None:
    """List available backup archives."""
    if not BACKUPS_DIR.exists():
        print("[backup] No backups directory found.")
        return

    archives = sorted(BACKUPS_DIR.glob("campaign_cannon_backup_*.tar.gz"))
    if not archives:
        print("[backup] No backup archives found.")
        return

    print(f"\n{'Archive':<55} {'Size':>10}")
    print("-" * 67)
    for archive in archives:
        size = archive.stat().st_size
        if size < 1024 * 1024:
            size_str = f"{size / 1024:.1f} KB"
        else:
            size_str = f"{size / (1024 * 1024):.1f} MB"
        print(f"{archive.name:<55} {size_str:>10}")
    print(f"\nTotal: {len(archives)} backup(s)")


def main():
    parser = argparse.ArgumentParser(
        description="Campaign Cannon backup & restore",
    )
    parser.add_argument(
        "--restore",
        metavar="PATH_OR_LATEST",
        help="Restore from archive (use 'latest' for most recent)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available backups",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )

    args = parser.parse_args()

    if args.list:
        list_backups()
    elif args.restore:
        restore_backup(args.restore, args.db_path)
    else:
        create_backup(args.db_path)


if __name__ == "__main__":
    main()
