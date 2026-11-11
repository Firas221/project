"""Repository base class.

Repositories are the only place SQL is written. Table and column names come
exclusively from class attributes (never from user input) and all values are
bound as parameters, so SQL injection is structurally impossible.
"""
import sqlite3
from typing import Iterable, Optional

from ..core.errors import NotFound


class BaseRepository:
    table: str = ""
    columns: tuple = ()          # writable columns
    select_sql: str = ""         # optional richer SELECT (with joins); must alias the main table as "t"
    default_order: str = "t.id"
    entity_label: str = "Record"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ------------------------------------------------------------ low-level helpers
    def _select(self) -> str:
        return self.select_sql or f"SELECT t.* FROM {self.table} t"

    def fetch_all(self, sql: str, args: Iterable = ()) -> list:
        return [dict(r) for r in self.conn.execute(sql, tuple(args)).fetchall()]

    def fetch_one(self, sql: str, args: Iterable = ()) -> Optional[dict]:
        row = self.conn.execute(sql, tuple(args)).fetchone()
        return dict(row) if row else None

    def scalar(self, sql: str, args: Iterable = (), default=None):
        row = self.conn.execute(sql, tuple(args)).fetchone()
        return default if row is None or row[0] is None else row[0]

    def execute(self, sql: str, args: Iterable = ()):
        return self.conn.execute(sql, tuple(args))

    def _check_columns(self, keys: Iterable[str]) -> None:
        allowed = set(self.columns) | {"id"}
        bad = [k for k in keys if k not in allowed]
        if bad:
            raise ValueError(f"Unknown column(s) for {self.table}: {bad}")

    # ------------------------------------------------------------ generic CRUD
    def get(self, id_: int) -> Optional[dict]:
        return self.fetch_one(self._select() + " WHERE t.id = ?", (id_,))

    def require(self, id_, label: str = None) -> dict:
        row = self.get(id_) if id_ is not None else None
        if row is None:
            raise NotFound(f"{label or self.entity_label} not found")
        return row

    def find_by(self, **where) -> list:
        self._check_columns(where)
        clause = " AND ".join(f"t.{k} = ?" for k in where) or "1=1"
        return self.fetch_all(f"{self._select()} WHERE {clause} ORDER BY {self.default_order}", where.values())

    def first_by(self, **where) -> Optional[dict]:
        rows = self.find_by(**where)
        return rows[0] if rows else None

    def all(self) -> list:
        return self.fetch_all(f"{self._select()} ORDER BY {self.default_order}")

    def exists(self, exclude_id: int = None, **where) -> bool:
        self._check_columns(where)
        clause = " AND ".join(f"{k} = ?" for k in where)
        args = list(where.values())
        if exclude_id is not None:
            clause += " AND id <> ?"
            args.append(exclude_id)
        return self.scalar(f"SELECT 1 FROM {self.table} WHERE {clause} LIMIT 1", args) is not None

    def count(self, **where) -> int:
        self._check_columns(where)
        clause = " AND ".join(f"{k} = ?" for k in where) or "1=1"
        return self.scalar(f"SELECT COUNT(*) FROM {self.table} WHERE {clause}", where.values(), 0)

    def insert(self, **data) -> int:
        self._check_columns(data)
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        return self.execute(f"INSERT INTO {self.table} ({cols}) VALUES ({marks})", data.values()).lastrowid

    def update(self, id_: int, **data) -> None:
        if not data:
            return
        self._check_columns(data)
        sets = ", ".join(f"{k} = ?" for k in data)
        self.execute(f"UPDATE {self.table} SET {sets} WHERE id = ?", list(data.values()) + [id_])

    def delete(self, id_: int) -> None:
        self.execute(f"DELETE FROM {self.table} WHERE id = ?", (id_,))


def page_of(repo: "BaseRepository", qb: "QueryBuilder", order_by: str, page, per_page=None) -> dict:
    """One page of a filtered list, plus the totals a pager needs."""
    try:
        per_page = max(1, min(int(per_page or 50), 200))
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page, per_page = 1, 50
    total = repo.scalar(f"SELECT COUNT(*) FROM ({qb.sql()})", qb.args, 0)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    rows = repo.fetch_all(qb.sql(order_by) + f" LIMIT {per_page} OFFSET {(page - 1) * per_page}", qb.args)
    return {"items": rows, "total": total, "page": page, "per_page": per_page, "pages": pages}


class QueryBuilder:
    """Tiny helper to assemble WHERE clauses from optional filters."""

    def __init__(self, base_sql: str):
        self.base = base_sql
        self.where, self.args = [], []

    def add(self, clause: str, *args) -> "QueryBuilder":
        self.where.append(clause)
        self.args.extend(args)
        return self

    def add_if(self, condition, clause: str, *args) -> "QueryBuilder":
        if condition not in (None, "", False):
            self.add(clause, *args)
        return self

    def sql(self, order_by: str = None, limit: int = None) -> str:
        sql = self.base
        if self.where:
            sql += " WHERE " + " AND ".join(self.where)
        if order_by:
            sql += " ORDER BY " + order_by
        if limit:
            sql += f" LIMIT {int(limit)}"
        return sql
