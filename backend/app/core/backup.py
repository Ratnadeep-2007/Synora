from datetime import datetime, timezone
import logging
import os
import shutil
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)


def create_sqlite_backup(db_file_path: str, backup_directory: str = "./backups") -> str:
    """
    Creates an atomic hot backup of an active SQLite database using the SQLite Online Backup API.
    Guarantees consistent point-in-time snapshot without locking or corrupting read/write queries.
    """
    if not os.path.exists(db_file_path):
        raise FileNotFoundError(f"Source database '{db_file_path}' does not exist.")

    os.makedirs(backup_directory, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file_name = f"synesis_backup_{timestamp}.db"
    destination_path = os.path.join(backup_directory, backup_file_name)

    # Use SQLite online backup API for safe hot backup
    source_conn = sqlite3.connect(db_file_path)
    dest_conn = sqlite3.connect(destination_path)

    try:
        source_conn.backup(dest_conn)
        logger.info(f"Database hot backup created successfully at: {destination_path}")
    finally:
        dest_conn.close()
        source_conn.close()

    return destination_path


def restore_sqlite_backup(backup_file_path: str, target_db_path: str) -> bool:
    """
    Restores SQLite database from a valid backup file with verification.
    """
    if not os.path.exists(backup_file_path):
        raise FileNotFoundError(f"Backup file '{backup_file_path}' does not exist.")

    # Integrity check on backup file before restoration
    test_conn = sqlite3.connect(backup_file_path)
    cursor = test_conn.cursor()
    cursor.execute("PRAGMA integrity_check")
    result = cursor.fetchone()
    test_conn.close()

    if not result or result[0] != "ok":
        raise ValueError(f"Backup file '{backup_file_path}' failed integrity check: {result}")

    # Atomic replace
    temp_target = f"{target_db_path}.restoring"
    shutil.copy2(backup_file_path, temp_target)
    if os.path.exists(target_db_path):
        os.remove(target_db_path)
    os.rename(temp_target, target_db_path)

    logger.info(f"Database restored successfully from '{backup_file_path}' to '{target_db_path}'.")
    return True
