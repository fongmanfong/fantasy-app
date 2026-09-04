"""
Analysis over the latest snapshot: projections, Monte Carlo weeks, and the
searches built on them.

    from fantasy.store import db
    from fantasy.analysis import matchup, waiver

    with db.connect(read_only=True) as con:
        matchup.head_to_head(con, team_b="Guan Yu")
        waiver.add_drop(con)

Each entry point takes an open connection and returns plain dicts, so the CLI,
the JSON server and a REPL all use the same calls.
"""
from . import matchup, projection, simulate, waiver

__all__ = ["matchup", "projection", "simulate", "waiver"]
