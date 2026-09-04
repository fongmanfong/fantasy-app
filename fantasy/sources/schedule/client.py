"""Fetches the league-wide game schedule from stats.nba.com, via nba_api."""
from datetime import date


def current_season(today: date | None = None) -> str:
    """
    The NBA labels a season by its starting year, e.g. games from Oct 2026
    through Jun 2027 are the '2026-27' season. New seasons announce their
    schedule in August, months before opening night, so treat Aug 1 as the
    rollover rather than the season's actual October start.
    """
    today = today or date.today()
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def fetch_schedule(season: str) -> dict:
    """
    Raw ScheduleLeagueV2 payload for one season, e.g. season='2026-27'.

    Imported lazily: nba_api's endpoints package imports pandas as a side
    effect, which costs real startup time on every `fantasy` invocation if
    pulled in at module load rather than only when a schedule command runs.
    """
    from nba_api.stats.endpoints import scheduleleaguev2

    return scheduleleaguev2.ScheduleLeagueV2(season=season, timeout=30).get_dict()
