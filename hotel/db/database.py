"""SQLite connection management and transactions (unit of work)."""
import logging
import os
import sqlite3
from contextlib import contextmanager

from .schema import MIGRATIONS

log = logging.getLogger("hotel.db")


class Database:
    """Creates connections and runs units of work.

    Writes use ``BEGIN IMMEDIATE`` so that concurrent write transactions are
    serialised by SQLite — this is what makes availability checks race-free
    (no double bookings, no negative stock).
    """

    def __init__(self, path: str):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    @contextmanager
    def unit_of_work(self, write: bool = True):
        conn = self.connect()
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if conn.in_transaction:
                conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------ migrations
    def migrate(self) -> int:
        """Applies pending migrations. Returns the number applied."""
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL,"
                " applied_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')))"
            )
            applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            if not applied and conn.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone():
                raise RuntimeError(
                    f"{self.path} was created by an older, incompatible version. Move it away or use --db to choose a new file."
                )
            count = 0
            for version, name, sql in MIGRATIONS:
                if version in applied:
                    continue
                log.info("Applying migration %s: %s", version, name)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _split_sql(sql):
                        conn.execute(statement)
                    conn.execute("INSERT INTO schema_migrations(version, name) VALUES (?, ?)", (version, name))
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                count += 1
            return count
        finally:
            conn.close()


def _split_sql(script: str):
    """Splits a migration script into statements (our schema has no ';' inside literals)."""
    lines = [ln for ln in script.splitlines() if not ln.strip().startswith("--")]
    for stmt in "\n".join(lines).split(";"):
        if stmt.strip():
            yield stmt
