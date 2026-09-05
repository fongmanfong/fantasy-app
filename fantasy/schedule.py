"""Pulls the NBA league schedule into DuckDB.

Shaped like rankings.py: its own pull sequence (`nba_schedule_pulls`), keyed by
season rather than league_key, because a schedule pull isn't specific to one
Yahoo league and happens on its own cadence (whenever the NBA revises it).
"""
import logging
from dataclasses import dataclass

from .sources.schedule import client, parse
from .store import db

logger = logging.getLogger(__name__)


@dataclass
class ScheduleResult:
    """What one schedule pull wrote, or why it did not."""
    pull_id: int
    season: str
    games: int = 0
    error: str | None = None

    @property
    def status(self) -> str:
        """What gets written to the pull row: a failed fetch is still a pull."""
        return "error" if self.error else "success"


def run(season: str | None = None, on_step=None) -> ScheduleResult:
    """
    Fetch one season's NBA schedule and append it.

    `season` defaults to the current one by date (see `client.current_season`,
    which rolls over in August, when the NBA publishes). Opens a **writable**
    connection, so it cannot run alongside another `fantasy` command.

    A fetch or parse failure is recorded on the pull row and returned on the
    result rather than raised — the previous schedule stays the newest
    successful one, so `projection.team_schedule` keeps working.
    """
    step = on_step or (lambda msg: None)
    season = season or client.current_season()

    with db.connect() as con:
        db.init_schema(con)
        pull_id = db.new_schedule_pull(con, season)

        step(f"Fetching {season} schedule")
        try:
            payload = client.fetch_schedule(season)
            rows = parse.parse_schedule(payload)
        except Exception as exc:
            logger.warning("schedule fetch failed: %s", exc)
            db.complete_schedule_pull(con, pull_id, "error", str(exc)[:1000])
            return ScheduleResult(pull_id=pull_id, season=season, error=str(exc))

        n = db.insert_schedule_rows(con, rows, pull_id, season)
        db.complete_schedule_pull(con, pull_id, "success")

    return ScheduleResult(pull_id=pull_id, season=season, games=n)
