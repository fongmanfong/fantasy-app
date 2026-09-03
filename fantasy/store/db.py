"""DuckDB access layer.

DuckDB takes an exclusive lock on the database file, so the connection is opened for
the duration of a command and closed again — never held open across the process.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .. import config

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

SNAPSHOT_TABLES = [
    "leagues", "league_settings", "league_stat_categories",
    "league_roster_positions", "teams", "players", "rosters", "player_stats",
]


@contextmanager
def connect(read_only: bool = False):
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(config.DB_PATH), read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def init_schema(con) -> None:
    """Idempotent — safe to run on every command."""
    con.execute(SCHEMA_PATH.read_text())


def new_pull(con, league_key: str) -> int:
    pull_id = con.execute("SELECT nextval('pull_id_seq')").fetchone()[0]
    con.execute(
        "INSERT INTO pulls (pull_id, league_key, pulled_at, status) VALUES (?, ?, ?, 'running')",
        [pull_id, league_key, datetime.now(timezone.utc)],
    )
    return pull_id


def complete_pull(con, pull_id: int, status: str, note: str | None = None) -> None:
    con.execute(
        "UPDATE pulls SET status = ?, note = ? WHERE pull_id = ?",
        [status, note, pull_id],
    )


def columns_of(con, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info('{table}')").fetchall()]


def insert_rows(con, table: str, rows: list[dict], pull_id: int, league_key: str) -> int:
    """
    Append rows, stamping pull_id and league_key.

    Row dicts may carry extra keys (the parsers return a superset); anything not in the
    table is dropped, and missing columns become NULL.
    """
    if not rows:
        return 0

    cols = columns_of(con, table)
    placeholders = ", ".join("?" for _ in cols)
    payload = []
    for row in rows:
        stamped = {**row, "pull_id": pull_id, "league_key": league_key}
        payload.append([stamped.get(c) for c in cols])

    con.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        payload,
    )
    return len(payload)


def table_names(con) -> list[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_type, table_name"
    ).fetchall()
    return [r[0] for r in rows]


def row_count(con, name: str) -> int:
    return con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
