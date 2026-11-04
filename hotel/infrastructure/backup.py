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

    def run(self) -> dict:
        """Uses SQLite's online backup API, so it is safe while the hotel is operating."""
        os.makedirs(self.backup_dir, exist_ok=True)
        name = f"hotel-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
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
        self._rotate()
        log.info("Backup written: %s", target)
        return {"file": name, "size": os.path.getsize(target)}

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
