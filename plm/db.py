"""SQLite connection and schema initialisation."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")
DEFAULT_DB = Path("build") / "honeycomb_plm.sqlite"


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # off by default in SQLite, per connection
    return conn


def init_db(path, force: bool = False) -> sqlite3.Connection:
    """Create an empty database. The .sqlite file is a derived artifact, so --force may replace it."""
    path = Path(path)
    if path.exists():
        if not force:
            raise FileExistsError(f"{path} already exists; pass --force to rebuild it from scratch")
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return conn
