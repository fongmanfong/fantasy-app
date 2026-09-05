"""
`fantasy` — snapshot a Yahoo Fantasy NBA league into DuckDB and analyse it.

Two halves. The **pull** side is append-only and writes: `pull.py` for the
league itself, `rankings.py` and `schedule.py` for the outside sources in
`sources/`. The **read** side never writes: `query.py` for the snapshot as it
stands, `analysis/` for the Monte Carlo model of a fantasy week, `report.py`
for the standing document, `server.py` for the local web view.

Everything on the read side takes an open connection and returns plain dicts,
so the CLI, the JSON server, the report and a REPL all use the same calls:

    from fantasy.store import db
    from fantasy.analysis import matchup

    with db.connect(read_only=True) as con:
        matchup.versus_field(con)

See `docs/ALGORITHMS.md` for what the model does and, more importantly, what it
cannot do — nothing in this package has been backtested against real weeks.
"""
__version__ = "0.1.0"
