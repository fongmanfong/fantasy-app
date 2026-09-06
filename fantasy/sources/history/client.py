"""Fetches per-season player totals from stats.nba.com, via nba_api."""
from datetime import date

# The Aug-1 rollover rule lives with the schedule client because that is where it
# was first needed; both packages are stats.nba.com and share the NBA's season
# labelling, so import it rather than keep a second copy of the same gotcha.
from ..schedule.client import current_season


def recent_seasons(n: int = 4, today: date | None = None) -> list[str]:
    """
    The `n` most recent seasons worth asking for, oldest first.

    `current_season` rolls over on Aug 1, when the NBA publishes the next
    schedule — months before a game is played. In August and September the
    labelled current season therefore has no stats at all, so the newest season
    to ask for is the one before it. From October on the current season is
    included, partial, which is usually what a caller wants mid-year.
    """
    today = today or date.today()
    latest = int(current_season(today)[:4])
    if today.month in (8, 9):
        latest -= 1
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(latest - n + 1, latest + 1)]


def fetch_player_seasons(season: str) -> dict:
    """
    Raw LeagueDashPlayerStats payload for one season, e.g. season='2025-26'.

    League-wide rather than per-player: this endpoint returns every player who
    appeared that season in a single request, which is ~570 rows for one call
    instead of one call per player. Season *totals*, not per-game — per-game is
    a division by GP that loses nothing, while the rounding in nba.com's own
    PerGame mode does.

    Imported lazily for the same reason as `schedule.client.fetch_schedule`:
    nba_api's endpoints package imports pandas as a side effect, which costs
    real startup time on every `fantasy` invocation.
    """
    from nba_api.stats.endpoints import leaguedashplayerstats

    return leaguedashplayerstats.LeagueDashPlayerStats(
        season=season,
        season_type_all_star="Regular Season",
        per_mode_detailed="Totals",
        timeout=60,
    ).get_dict()
