"""Pulls past-season NBA player totals into DuckDB.

Shaped like schedule.py — its own pull sequence (`nba_season_pulls`), keyed by
NBA season rather than league_key, because nba.com's numbers are the same for
every league. The one difference is that a run covers several seasons, and each
season is its own pull: they succeed and fail independently, so a rate-limited
2019-20 does not cost you the other three.

What this is for. A Yahoo snapshot holds one season, and once that season is
over its four stat windows are identical full-season figures — so nothing in the
store can say whether a player is climbing, declining, or has ever been durable.
Several seasons of the same player is the missing axis.

A finished season never changes, so by default one that is already stored is
skipped rather than fetched again — see `should_pull`.
"""
import logging
import time
from dataclasses import dataclass, field

from . import query
from .names import normalize
from .sources.history import client, parse
from .store import db

logger = logging.getLogger(__name__)

# stats.nba.com throttles a burst of requests from one address. A season is one
# request, so a run is a handful of them; a second between seasons is cheap
# insurance against being cut off partway through.
PAUSE_SECONDS = 1.0


@dataclass
class SeasonResult:
    """What one season's pull wrote, why it did not, or that it was skipped."""
    season: str
    pull_id: int | None = None   # None when skipped — a skip opens no pull row
    players: int = 0
    matched: int = 0             # rows joined to a player_key in the league snapshot
    error: str | None = None
    skipped: bool = False

    @property
    def status(self) -> str:
        """What gets written to the pull row: a failed fetch is still a pull."""
        return "error" if self.error else "success"


@dataclass
class HistoryResult:
    """Every season a run considered, in the order it considered them."""
    seasons: list[SeasonResult] = field(default_factory=list)

    @property
    def players(self) -> int:
        return sum(s.players for s in self.seasons)

    @property
    def fetched(self) -> list[SeasonResult]:
        return [s for s in self.seasons if not s.skipped]

    @property
    def skipped(self) -> list[SeasonResult]:
        return [s for s in self.seasons if s.skipped]

    @property
    def failed(self) -> list[SeasonResult]:
        return [s for s in self.seasons if s.error]


def stored_seasons(con) -> set[str]:
    """
    Seasons that already have rows from a successful pull.

    Rows rather than a pull row's status, because a pull that succeeded and
    stored nothing — asking nba.com for a season before a game has been played
    returns an empty result set — has not actually got you the season.
    """
    rows = con.execute(
        "SELECT season FROM v_nba_player_seasons GROUP BY season HAVING count(*) > 0"
    ).fetchall()
    return {season for (season,) in rows}


def should_pull(season: str, stored: set[str], in_progress: str,
                refresh: bool = False) -> bool:
    """
    Whether a season is worth spending a request on.

    A finished season's totals are final, so once it is stored there is nothing
    to gain by asking again — miss a year and the next run fetches only the
    years you missed. Two exceptions:

    - **The season in progress** is always re-fetched. Its totals are still
      accumulating, so a stored copy is a snapshot of a moving number, and
      skipping it would freeze the store at whenever you first pulled.
    - **`refresh`** overrides everything, which is also how you re-match old
      seasons against a newer league snapshot: `player_key` is resolved at
      insert time, so a season stored before a `fantasy pull` still carries the
      matches it made then.
    """
    return refresh or season == in_progress or season not in stored


def run(seasons: list[str] | None = None, count: int = 4, refresh: bool = False,
        on_step=None) -> HistoryResult:
    """
    Fetch NBA player totals for each season named, and append each.

    `seasons` defaults to the `count` most recent seasons that have been played
    (see `client.recent_seasons`, which knows that the season labelled current
    in August has not started yet). Seasons already stored are skipped unless
    `refresh` is set — see `should_pull` — so the normal run costs a request
    only for what is actually missing. Opens a **writable** connection held for
    the whole run, so it cannot run alongside another `fantasy` command.

    Rows that do not match a player in the league snapshot are stored anyway,
    with a null `player_key`, exactly as in `rankings.run`. Here most of those
    are simply players Yahoo has no row for — nba.com carries every player who
    appeared in a season, and the snapshot carries the ones a 12-team league
    rostered or listed. The reverse miss is the interesting one: a Yahoo player
    absent from a season means he did not play that year, which is a fact worth
    reading rather than a matching failure.
    """
    step = on_step or (lambda msg: None)
    seasons = seasons or client.recent_seasons(count)
    in_progress = client.current_season()
    result = HistoryResult()

    with db.connect() as con:
        db.init_schema(con)
        stored = stored_seasons(con)
        by_name = query.player_keys_by_name(con)
        fetched = 0

        for season in seasons:
            if not should_pull(season, stored, in_progress, refresh):
                result.seasons.append(SeasonResult(season=season, skipped=True))
                continue

            # Spacing applies between requests, so a run of skips costs nothing.
            if fetched:
                time.sleep(PAUSE_SECONDS)
            fetched += 1

            pull_id = db.new_season_pull(con, season)
            step(f"Fetching {season} player totals")
            try:
                payload = client.fetch_player_seasons(season)
                rows = parse.parse_player_seasons(payload)
            except Exception as exc:
                logger.warning("player-totals fetch failed for %s: %s", season, exc)
                db.complete_season_pull(con, pull_id, "error", str(exc)[:1000])
                result.seasons.append(
                    SeasonResult(season=season, pull_id=pull_id, error=str(exc)))
                continue

            season_result = SeasonResult(season=season, pull_id=pull_id)
            for row in rows:
                name_key = normalize(row["player_name"])
                row["player_name_key"] = name_key
                row["player_key"] = by_name.get(name_key)
                if row["player_key"]:
                    season_result.matched += 1

            season_result.players = db.insert_player_season_rows(con, rows, pull_id, season)
            note = (f"{season_result.matched}/{season_result.players} matched to the "
                    f"league snapshot" if rows else "no rows parsed")
            db.complete_season_pull(con, pull_id, season_result.status, note)
            result.seasons.append(season_result)

    return result
