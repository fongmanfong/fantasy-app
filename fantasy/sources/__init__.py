"""
External data sources — everything the store pulls in besides your Yahoo league.

Each subpackage is independent: its own pull sequence in schema.sql, its own
orchestrator alongside this package (`rankings.py`, `schedule.py`), and no shared
code between them beyond that shape. `rankings/` is a registry of interchangeable
ranking-site scrapers behind one `SOURCES` dict; `schedule/` is a single stats.nba.com
integration, split into `client.py`/`parse.py` the same way `yahoo/` is.
"""
