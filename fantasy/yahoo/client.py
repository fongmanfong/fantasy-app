"""Authenticated access to the Yahoo Fantasy Sports API."""
import logging

from . import auth, parse

API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

# Yahoo caps multi-entity requests at 25.
BATCH_SIZE = 25

# CLI period name → Yahoo `type` parameter.
STAT_PERIODS = {
    "season": "season",
    "last_7": "lastweek",
    "last_14": "last14days",
    "last_30": "lastmonth",
}

logger = logging.getLogger(__name__)


def _chunks(items: list, size: int = BATCH_SIZE):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def game_key_of(league_key: str) -> str:
    """"466.l.28641" → "466". Yahoo's own key, never a hardcoded season."""
    return league_key.split(".", 1)[0]


class YahooClient:
    def __init__(self, session=None):
        self._session = session or auth.session()

    def _get(self, path: str, **params) -> dict:
        params["format"] = "json"
        resp = self._session.get(f"{API_BASE}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    # --- Discovery ---

    def my_leagues(self, game_code: str = "nba") -> list[dict]:
        data = self._get(f"/users;use_login=1/games;game_codes={game_code}/leagues")
        return parse.parse_my_leagues(data)

    def my_team_key(self, league_key: str) -> str | None:
        try:
            data = self._get(
                f"/users;use_login=1/games;game_keys={game_key_of(league_key)}"
                f"/leagues;league_keys={league_key}/teams"
            )
            return parse.parse_my_team_key(data)
        except Exception as exc:
            logger.warning("Could not determine your team in %s: %s", league_key, exc)
            return None

    # --- League ---

    def league_settings(self, league_key: str) -> dict:
        """Returns the raw fantasy_content; feed it to the parse_* settings helpers."""
        data = self._get(f"/league/{league_key}/settings")
        return data.get("fantasy_content", {})

    def standings(self, league_key: str) -> list[dict]:
        return parse.parse_standings(self._get(f"/league/{league_key}/standings"))

    # --- Rosters ---

    def team_roster(self, team_key: str) -> list[dict]:
        data = self._get(f"/team/{team_key}/roster/players")
        team = parse._as_list(data.get("fantasy_content", {}).get("team"))
        if len(team) < 2 or not isinstance(team[1], dict):
            return []
        roster = team[1].get("roster", {})
        if isinstance(roster, list):
            roster = roster[0] if roster else {}
        players = roster.get("0", {}).get("players", {}) if isinstance(roster, dict) else {}
        if not players and isinstance(roster, dict):
            players = roster.get("players", {})
        return parse.parse_players(players)

    def free_agents(self, league_key: str, limit: int | None = None) -> list[dict]:
        """
        Walk the free-agent pool.

        Yahoo returns at most 25 per call and gives no total, so page until a short
        page comes back. The previous version made a single count=50 call and silently
        truncated the pool.
        """
        rows: list[dict] = []
        seen: set[str] = set()
        start = 0

        while True:
            data = self._get(
                f"/league/{league_key}/players;status=FA;sort=AR"
                f";start={start};count={BATCH_SIZE}"
            )
            league = parse._as_list(data.get("fantasy_content", {}).get("league"))
            players_raw = league[1].get("players", {}) if len(league) > 1 and isinstance(league[1], dict) else {}
            page = parse.parse_players(players_raw)
            if not page:
                break

            new = [p for p in page if (p["player_key"] or p["player_id"]) not in seen]
            for p in new:
                seen.add(p["player_key"] or p["player_id"])
            rows.extend(new)

            if not new or len(page) < BATCH_SIZE:
                break
            if limit and len(rows) >= limit:
                rows = rows[:limit]
                break
            start += BATCH_SIZE

        return rows

    # --- Players ---

    def player_stats(self, league_key: str, player_keys: list[str], period: str) -> list[dict]:
        yahoo_period = STAT_PERIODS.get(period, period)
        rows = []
        for batch in _chunks(player_keys):
            keys = ",".join(batch)
            try:
                data = self._get(
                    f"/league/{league_key}/players;player_keys={keys};out=stats;type={yahoo_period}"
                )
                league = parse._as_list(data.get("fantasy_content", {}).get("league"))
                players_raw = league[1].get("players", {}) if len(league) > 1 and isinstance(league[1], dict) else {}
                rows.extend(parse.parse_player_stats(players_raw, period))
            except Exception as exc:
                logger.warning("Stats batch failed (%s, %d keys): %s", period, len(batch), exc)
                continue
        return rows

    def player_metadata(self, league_key: str, player_keys: list[str]) -> list[dict]:
        """Fetch full player attributes (notably birth_date, absent from roster responses)."""
        rows = []
        for batch in _chunks(player_keys):
            keys = ",".join(batch)
            try:
                data = self._get(f"/league/{league_key}/players;player_keys={keys}")
                league = parse._as_list(data.get("fantasy_content", {}).get("league"))
                players_raw = league[1].get("players", {}) if len(league) > 1 and isinstance(league[1], dict) else {}
                rows.extend(parse.parse_players(players_raw))
            except Exception as exc:
                logger.warning("Metadata batch failed (%d keys): %s", len(batch), exc)
                continue
        return rows
