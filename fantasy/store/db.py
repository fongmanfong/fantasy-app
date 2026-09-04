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


class NoDatabase(RuntimeError):
    """Raised when a read-only command runs before the first pull."""


@contextmanager
def connect(read_only: bool = False):
    # DuckDB refuses to open a nonexistent file read-only, which would otherwise
    # surface as an opaque IO error on a fresh checkout.
    if read_only and not config.DB_PATH.exists():
        raise NoDatabase(
            f"No database at {config.DB_PATH} yet. Run `fantasy pull` first."
        )

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


def new_ranking_pull(con, source: str, source_url: str) -> int:
    ranking_pull_id = con.execute("SELECT nextval('ranking_pull_id_seq')").fetchone()[0]
    con.execute(
        "INSERT INTO ranking_pulls (ranking_pull_id, source, source_url, pulled_at, status) "
        "VALUES (?, ?, ?, ?, 'running')",
        [ranking_pull_id, source, source_url, datetime.now(timezone.utc)],
    )
    return ranking_pull_id


def complete_ranking_pull(con, ranking_pull_id: int, status: str, note: str | None = None) -> None:
    con.execute(
        "UPDATE ranking_pulls SET status = ?, note = ? WHERE ranking_pull_id = ?",
        [status, note, ranking_pull_id],
    )


def insert_ranking_rows(con, rows: list[dict]) -> int:
    """Like insert_rows, but player_rankings rows already carry their own
    ranking_pull_id/source rather than a shared pull_id/league_key stamp."""
    if not rows:
        return 0
    cols = columns_of(con, "player_rankings")
    placeholders = ", ".join("?" for _ in cols)
    payload = [[row.get(c) for c in cols] for row in rows]
    con.executemany(
        f"INSERT INTO player_rankings ({', '.join(cols)}) VALUES ({placeholders})",
        payload,
    )
    return len(payload)


def new_schedule_pull(con, season: str) -> int:
    pull_id = con.execute("SELECT nextval('nba_schedule_pull_id_seq')").fetchone()[0]
    con.execute(
        "INSERT INTO nba_schedule_pulls (pull_id, season, pulled_at, status) "
        "VALUES (?, ?, ?, 'running')",
        [pull_id, season, datetime.now(timezone.utc)],
    )
    return pull_id


def complete_schedule_pull(con, pull_id: int, status: str, note: str | None = None) -> None:
    con.execute(
        "UPDATE nba_schedule_pulls SET status = ?, note = ? WHERE pull_id = ?",
        [status, note, pull_id],
    )


def insert_schedule_rows(con, rows: list[dict], pull_id: int, season: str) -> int:
    """Like insert_rows, but stamps pull_id/season rather than pull_id/league_key."""
    if not rows:
        return 0
    cols = columns_of(con, "nba_schedule")
    placeholders = ", ".join("?" for _ in cols)
    payload = []
    for row in rows:
        stamped = {**row, "pull_id": pull_id, "season": season}
        payload.append([stamped.get(c) for c in cols])
    con.executemany(
        f"INSERT INTO nba_schedule ({', '.join(cols)}) VALUES ({placeholders})",
        payload,
    )
    return len(payload)


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
