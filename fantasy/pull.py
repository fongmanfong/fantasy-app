"""Orchestrates a full snapshot of a league into DuckDB."""
import logging
from dataclasses import dataclass, field

from .store import db
from .yahoo import auth, parse
from .yahoo.client import STAT_PERIODS, YahooClient

logger = logging.getLogger(__name__)

DEFAULT_PERIODS = ["season", "last_7", "last_14", "last_30"]


@dataclass
class PullResult:
    pull_id: int
    league_key: str
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "partial" if self.errors else "success"


def resolve_league_key(client: YahooClient, requested: str | None) -> str:
    """Accept a full league_key, a bare league id, or nothing when you have one league."""
    leagues = client.my_leagues()
    if not leagues:
        raise RuntimeError("Your Yahoo account has no NBA fantasy leagues.")

    if not requested:
        if len(leagues) == 1:
            return leagues[0]["league_key"]
        listing = "\n".join(f"  {lg['league_key']}  {lg['name']} ({lg['season']})" for lg in leagues)
        raise RuntimeError(f"You have {len(leagues)} leagues — pass one explicitly:\n{listing}")

    for lg in leagues:
        if requested in (lg["league_key"], lg["league_id"]):
            return lg["league_key"]

    raise RuntimeError(f"League {requested!r} not found on your account.")


def _merge_players(store: dict, rows: list[dict]) -> None:
    """One row per player per pull; later sources fill in gaps without clobbering."""
    for row in rows:
        key = row.get("player_key") or row.get("player_id")
        if not key:
            continue
        existing = store.setdefault(key, {})
        for field_name, value in row.items():
            if field_name == "selected_position":
                continue
            if value not in (None, [], ""):
                existing[field_name] = value


def run(
    league_key: str | None = None,
    periods: list[str] | None = None,
    skip_stats: bool = False,
    fa_limit: int | None = None,
    on_step=None,
) -> PullResult:
    periods = periods or DEFAULT_PERIODS
    step = on_step or (lambda msg: None)

    step("Refreshing Yahoo token")
    auth.refresh_now()
    client = YahooClient()

    step("Resolving league")
    league_key = resolve_league_key(client, league_key)

    with db.connect() as con:
        db.init_schema(con)
        pull_id = db.new_pull(con, league_key)
        result = PullResult(pull_id=pull_id, league_key=league_key)

        def record(table: str, rows: list[dict]) -> None:
            n = db.insert_rows(con, table, rows, pull_id, league_key)
            result.counts[table] = result.counts.get(table, 0) + n

        def guarded(label: str, fn):
            """One failing step is recorded and skipped; the rest of the pull continues."""
            try:
                return fn()
            except Exception as exc:
                logger.warning("%s failed: %s", label, exc)
                result.errors.append(f"{label}: {exc}")
                return None

        players: dict[str, dict] = {}
        roster_rows: list[dict] = []

        # --- League + settings ---
        step("Fetching league settings")

        def _league():
            content = client.league_settings(league_key)
            record("leagues", [parse.parse_league(content)])
            record("league_settings", [parse.parse_settings(content)])
            record("league_stat_categories", parse.parse_stat_categories(content))
            record("league_roster_positions", parse.parse_roster_positions(content))

        guarded("league settings", _league)

        # --- Teams + standings ---
        step("Fetching standings")
        teams = guarded("standings", lambda: client.standings(league_key)) or []
        my_team_key = guarded("my team", lambda: client.my_team_key(league_key))
        for team in teams:
            team["is_my_team"] = bool(my_team_key) and team.get("team_key") == my_team_key
        record("teams", teams)

        # --- Rosters ---
        for team in teams:
            team_key = team.get("team_key")
            if not team_key:
                continue
            step(f"Fetching roster: {team.get('name') or team_key}")
            rows = guarded(f"roster {team_key}", lambda tk=team_key: client.team_roster(tk)) or []
            _merge_players(players, rows)
            for row in rows:
                roster_rows.append({
                    "team_key": team_key,
                    "player_key": row.get("player_key"),
                    "selected_position": row.get("selected_position"),
                    "is_free_agent": False,
                })

        # --- Free agents ---
        step("Fetching free agents")
        fa = guarded("free agents", lambda: client.free_agents(league_key, limit=fa_limit)) or []
        _merge_players(players, fa)
        for row in fa:
            roster_rows.append({
                "team_key": None,
                "player_key": row.get("player_key"),
                "selected_position": None,
                "is_free_agent": True,
            })

        # --- Backfill birth_date, which roster responses omit ---
        missing_dob = [k for k, p in players.items() if not p.get("birth_date")]
        if missing_dob:
            step(f"Fetching metadata for {len(missing_dob)} players")
            meta = guarded(
                "player metadata",
                lambda: client.player_metadata(league_key, missing_dob),
            ) or []
            _merge_players(players, meta)

        record("players", list(players.values()))
        record("rosters", roster_rows)

        # --- Stats ---
        if not skip_stats and players:
            player_keys = list(players.keys())
            for period in periods:
                if period not in STAT_PERIODS:
                    result.errors.append(f"unknown stat period: {period}")
                    continue
                step(f"Fetching stats: {period} ({len(player_keys)} players)")
                rows = guarded(
                    f"stats {period}",
                    lambda p=period: client.player_stats(league_key, player_keys, p),
                ) or []
                record("player_stats", rows)

        db.complete_pull(
            con, pull_id, result.status,
            "; ".join(result.errors)[:1000] if result.errors else None,
        )

    return result
