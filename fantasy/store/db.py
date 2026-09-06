"""DuckDB access layer.

DuckDB takes an exclusive lock on the database file, so the connection is opened for
the duration of a command and closed again — never held open across the process.
"""
import json
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
    """
    Open the snapshot database for the duration of a command.

    `read_only=True` is what lets several commands — and a `duckdb` shell —
    share the file; a writable connection takes an exclusive lock, so only one
    `pull`, `rankings pull`, `schedule pull` or `history pull` can run at a
    time. Raises
    :class:`NoDatabase` rather than an opaque IO error when a read-only caller
    runs before the first pull.
    """
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
    """
    Open a league pull and return its id, for stamping onto every row it
    writes. Left at status 'running' until `complete_pull` closes it, which is
    what keeps a half-finished pull out of the `v_*` views.
    """
    pull_id = con.execute("SELECT nextval('pull_id_seq')").fetchone()[0]
    con.execute(
        "INSERT INTO pulls (pull_id, league_key, pulled_at, status) VALUES (?, ?, ?, 'running')",
        [pull_id, league_key, datetime.now(timezone.utc)],
    )
    return pull_id


def _complete(con, table: str, pk_col: str, pk: int,
              status: str, note: str | None) -> None:
    """Close out a pull row. The four sequences differ only in table and key."""
    con.execute(
        f"UPDATE {table} SET status = ?, note = ? WHERE {pk_col} = ?",
        [status, note, pk],
    )


def complete_pull(con, pull_id: int, status: str, note: str | None = None) -> None:
    """Mark a league pull finished. Needs a writable connection."""
    _complete(con, "pulls", "pull_id", pull_id, status, note)


def new_ranking_pull(con, source: str, source_url: str) -> int:
    """Open a ranking-site pull and return its id. See `new_pull`."""
    ranking_pull_id = con.execute("SELECT nextval('ranking_pull_id_seq')").fetchone()[0]
    con.execute(
        "INSERT INTO ranking_pulls (ranking_pull_id, source, source_url, pulled_at, status) "
        "VALUES (?, ?, ?, ?, 'running')",
        [ranking_pull_id, source, source_url, datetime.now(timezone.utc)],
    )
    return ranking_pull_id


def last_ranking_url(con, source: str) -> str | None:
    """
    The URL of the newest successful pull for a source, or None if it has never
    been pulled. What `remembers_url` sources default to — see fantasy/rankings.py.
    """
    row = con.execute(
        "SELECT source_url FROM ranking_pulls WHERE source = ? AND status = 'success' "
        "ORDER BY ranking_pull_id DESC LIMIT 1",
        [source],
    ).fetchone()
    return row[0] if row else None


def complete_ranking_pull(con, ranking_pull_id: int, status: str, note: str | None = None) -> None:
    """Mark a ranking-site pull finished. Needs a writable connection."""
    _complete(con, "ranking_pulls", "ranking_pull_id", ranking_pull_id, status, note)


def insert_ranking_rows(con, rows: list[dict]) -> int:
    """
    Append scraped ranking rows. Needs a writable connection.

    Unlike the other two inserters this stamps nothing: `player_rankings` rows
    already carry their own ranking_pull_id and source, because a ranking pull
    is not tied to a Yahoo league.
    """
    return _insert(con, "player_rankings", rows)


def new_schedule_pull(con, season: str) -> int:
    """Open an NBA schedule pull and return its id. See `new_pull`."""
    pull_id = con.execute("SELECT nextval('nba_schedule_pull_id_seq')").fetchone()[0]
    con.execute(
        "INSERT INTO nba_schedule_pulls (pull_id, season, pulled_at, status) "
        "VALUES (?, ?, ?, 'running')",
        [pull_id, season, datetime.now(timezone.utc)],
    )
    return pull_id


def complete_schedule_pull(con, pull_id: int, status: str, note: str | None = None) -> None:
    """Mark an NBA schedule pull finished. Needs a writable connection."""
    _complete(con, "nba_schedule_pulls", "pull_id", pull_id, status, note)


def insert_schedule_rows(con, rows: list[dict], pull_id: int, season: str) -> int:
    """
    Append NBA schedule rows, stamping pull_id and season rather than a
    league_key — the schedule is the same for every league. Writable connection.
    """
    return _insert(con, "nba_schedule", rows, {"pull_id": pull_id, "season": season})


def new_season_pull(con, season: str) -> int:
    """Open an NBA player-totals pull and return its id. See `new_pull`."""
    pull_id = con.execute("SELECT nextval('nba_season_pull_id_seq')").fetchone()[0]
    con.execute(
        "INSERT INTO nba_season_pulls (pull_id, season, pulled_at, status) "
        "VALUES (?, ?, ?, 'running')",
        [pull_id, season, datetime.now(timezone.utc)],
    )
    return pull_id


def complete_season_pull(con, pull_id: int, status: str, note: str | None = None) -> None:
    """Mark an NBA player-totals pull finished. Needs a writable connection."""
    _complete(con, "nba_season_pulls", "pull_id", pull_id, status, note)


def insert_player_season_rows(con, rows: list[dict], pull_id: int, season: str) -> int:
    """
    Append one season of NBA player totals, stamping pull_id and season — the
    parser never sees which season it parsed. Writable connection.
    """
    return _insert(con, "nba_player_seasons", rows, {"pull_id": pull_id, "season": season})


def new_composite_run(con, kind: str, sources: dict, params: dict) -> int:
    """
    Open a composite run and return its id. See `new_pull`.

    Unlike the four pull sequences this fetches nothing — but it is stamped and
    closed the same way, because what makes an old ordering readable is knowing
    which ranking pulls and which parameters produced it.
    """
    run_id = con.execute("SELECT nextval('composite_run_id_seq')").fetchone()[0]
    con.execute(
        "INSERT INTO composite_runs (run_id, kind, computed_at, status, sources, params) "
        "VALUES (?, ?, ?, 'running', ?, ?)",
        [run_id, kind, datetime.now(timezone.utc), json.dumps(sources), json.dumps(params)],
    )
    return run_id


def complete_composite_run(con, run_id: int, status: str, note: str | None = None) -> None:
    """Mark a composite run finished. Needs a writable connection."""
    _complete(con, "composite_runs", "run_id", run_id, status, note)


def insert_composite_rows(con, rows: list[dict], run_id: int) -> int:
    """Append the reranked players of one run, stamping run_id. Writable connection."""
    return _insert(con, "composite_rankings", rows, {"run_id": run_id})


def columns_of(con, table: str) -> list[str]:
    """The table's column names, in declaration order. Reads only the catalogue."""
    return [r[1] for r in con.execute(f"PRAGMA table_info('{table}')").fetchall()]


def _insert(con, table: str, rows: list[dict], stamp: dict | None = None) -> int:
    """
    The shared append: project each row onto the table's real columns and
    executemany. Row dicts may carry extra keys — the parsers return a superset
    — so anything not in the table is dropped and missing columns become NULL.
    `stamp` is merged into every row, which is how a pull id gets onto the data
    without every parser having to know about it.
    """
    if not rows:
        return 0

    cols = columns_of(con, table)
    placeholders = ", ".join("?" for _ in cols)
    payload = [[{**row, **(stamp or {})}.get(c) for c in cols] for row in rows]

    con.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        payload,
    )
    return len(payload)


def insert_rows(con, table: str, rows: list[dict], pull_id: int, league_key: str) -> int:
    """
    Append league-snapshot rows, stamping pull_id and league_key. Needs a
    writable connection.
    """
    return _insert(con, table, rows, {"pull_id": pull_id, "league_key": league_key})


def table_names(con) -> list[str]:
    """Every table and view in the database, tables first. Backs `fantasy tables`."""
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_type, table_name"
    ).fetchall()
    return [r[0] for r in rows]


def row_count(con, name: str) -> int:
    """Row count for one table or view."""
    return con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
