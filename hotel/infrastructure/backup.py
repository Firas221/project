"""Consistent online backups of the SQLite database with rotation."""
import datetime as dt
import glob
import logging
import os
import sqlite3

log = logging.getLogger("hotel.backup")


class BackupManager:
    def __init__(self, db_path: str, backup_dir: str, keep: int = 14):
        self.db_path, self.backup_dir, self.keep = db_path, backup_dir, max(1, keep)

    def run(self, rotate: bool = True) -> dict:
        """Uses SQLite's online backup API, so it is safe while the hotel is operating."""
        os.makedirs(self.backup_dir, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        name, n = f"hotel-{stamp}.db", 1
        while os.path.exists(os.path.join(self.backup_dir, name)):
            n += 1
            name = f"hotel-{stamp}-{n}.db"
        target = os.path.join(self.backup_dir, name)
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            ok = dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            dst.close()
            src.close()
        if not ok:
            os.remove(target)
            raise RuntimeError("Backup failed the integrity check")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        if rotate:
            self._rotate()
        log.info("Backup written: %s", target)
        return {"file": name, "size": os.path.getsize(target)}

    def resolve(self, name: str) -> str:
        """Maps a backup name from the admin screen to its file. Only files inside the backup folder qualify."""
        if not isinstance(name, str) or os.path.basename(name) != name or name not in {b["file"] for b in self.list()}:
            raise ValueError("Unknown backup file")
        return os.path.join(self.backup_dir, name)

    @staticmethod
    def inspect(path: str) -> int:
        """Checks that a file is an intact hotel database and returns its schema version."""
        if not os.path.isfile(path):
            raise ValueError(f"Backup file not found: {path}")
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("The backup file is damaged (integrity check failed)")
                version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            raise ValueError("This file is not a hotel database backup")
        if not version:
            raise ValueError("This file is not a hotel database backup")
        return version

    def restore(self, path: str, current_version: int) -> dict:
        """Replaces the live database with a backup.

        The current data is backed up first, so a restore can itself be undone. Uses SQLite's backup API,
        which is safe while the server is running: requests wait for the copy and then see the restored data.
        """
        version = self.inspect(path)
        if version > current_version:
            raise ValueError("This backup was made by a newer version of the system and cannot be restored here")
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        safety = self.run(rotate=False)["file"] if os.path.isfile(self.db_path) else None
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        dst = sqlite3.connect(self.db_path, timeout=60)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        log.warning("Database restored from %s (previous data saved as %s)", path, safety)
        return {"restored": os.path.basename(path), "safety_backup": safety, "schema": version}

    def _rotate(self) -> None:
        files = sorted(glob.glob(os.path.join(self.backup_dir, "hotel-*.db")))
        for old in files[:-self.keep]:
            os.remove(old)

    def list(self) -> list:
        files = sorted(glob.glob(os.path.join(self.backup_dir, "hotel-*.db")), reverse=True)
        return [{"file": os.path.basename(f), "size": os.path.getsize(f),
                 "created_at": dt.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")}
                for f in files]

    def latest_age_hours(self):
        files = sorted(glob.glob(os.path.join(self.backup_dir, "hotel-*.db")))
        if not files:
            return None
        return (dt.datetime.now().timestamp() - os.path.getmtime(files[-1])) / 3600
