"""
Pure parsers for Yahoo Fantasy JSON.

Yahoo returns deeply nested *positional* arrays mixed with dicts keyed by stringified
indices ("0", "1", ..., plus a "count"). Every function here takes raw JSON and returns
flat row dicts. No I/O, no database — this module is the hard-won knowledge from the
previous version of this app.
"""

# Yahoo stat IDs → readable names (NBA).
YAHOO_STAT_MAP = {
    "0": "GP", "1": "GS", "2": "MIN",
    "3": "FGM", "4": "FGA", "5": "FG%",
    "6": "FTM", "7": "FTA", "8": "FT%",
    "9": "3PTM", "10": "3PTA", "11": "3PT%",
    "12": "PTS", "13": "OREB", "14": "DREB",
    "15": "REB", "16": "AST", "17": "ST",
    "18": "BLK", "19": "TO", "20": "A/T",
    "22": "+/-", "23": "DD2", "24": "TD3",
}


def _as_list(node) -> list:
    """Yahoo returns single-element containers as either a dict or a 1-item list."""
    if node is None:
        return []
    return node if isinstance(node, list) else [node]


def _info_list(entity: list) -> list[dict]:
    """entity[0] is a list of single-key dicts (with empty arrays mixed in)."""
    if not entity:
        return []
    head = entity[0]
    items = head if isinstance(head, list) else [head]
    return [i for i in items if isinstance(i, dict)]


def _indexed(container: dict):
    """Iterate Yahoo's {"0": {...}, "1": {...}, "count": N} maps, skipping `count`."""
    if not isinstance(container, dict):
        return
    for key, val in container.items():
        if key == "count" or not isinstance(val, dict):
            continue
        yield val


def _unwrap(entry, key: str) -> dict | None:
    """Entries arrive as {"stat": {...}} or bare {...}."""
    if not isinstance(entry, dict):
        return None
    inner = entry.get(key, entry)
    return inner if isinstance(inner, dict) else None


def _num(value, default=0):
    try:
        return type(default)(value)
    except (TypeError, ValueError):
        return default


# --- Leagues -------------------------------------------------------------

def parse_my_leagues(data: dict) -> list[dict]:
    """
    From /users;use_login=1/games;game_keys=nba/leagues.

    Returns the league_key verbatim (e.g. "466.l.28641"). Using Yahoo's own key rather
    than rebuilding "nba.l.{id}" is what keeps this correct across seasons.
    """
    leagues = []
    users = data.get("fantasy_content", {}).get("users", {})
    for user in _indexed(users):
        user_data = _as_list(user.get("user"))
        for elem in user_data:
            if not isinstance(elem, dict) or "games" not in elem:
                continue
            for game in _indexed(elem["games"]):
                game_data = _as_list(game.get("game"))
                game_meta = next((g for g in game_data if isinstance(g, dict) and "game_key" in g), {})
                for game_elem in game_data:
                    if not isinstance(game_elem, dict) or "leagues" not in game_elem:
                        continue
                    for lg in _indexed(game_elem["leagues"]):
                        for item in _as_list(lg.get("league")):
                            if not isinstance(item, dict) or "league_key" not in item:
                                continue
                            leagues.append({
                                "league_key": item["league_key"],
                                "league_id": str(item.get("league_id", "")),
                                "name": item.get("name"),
                                "season": _num(item.get("season"), 0),
                                "num_teams": _num(item.get("num_teams"), 0),
                                "scoring_type": item.get("scoring_type"),
                                "game_key": game_meta.get("game_key"),
                                "game_code": game_meta.get("code"),
                            })
    return leagues


def parse_league(content: dict) -> dict:
    """From /league/{league_key}/settings — the league metadata half."""
    league = _as_list(content.get("league"))
    meta = league[0] if league and isinstance(league[0], dict) else {}
    return {
        "league_key": meta.get("league_key"),
        "league_id": str(meta.get("league_id", "")),
        "name": meta.get("name"),
        "season": _num(meta.get("season"), 0),
        "num_teams": _num(meta.get("num_teams"), 0),
        "scoring_type": meta.get("scoring_type"),
        "current_week": _num(meta.get("current_week"), 0),
        "start_date": meta.get("start_date"),
        "end_date": meta.get("end_date"),
        "is_finished": bool(_num(meta.get("is_finished"), 0)),
        "url": meta.get("url"),
    }


def _settings_blob(content: dict) -> dict:
    league = _as_list(content.get("league"))
    if len(league) < 2 or not isinstance(league[1], dict):
        return {}
    settings = league[1].get("settings", {})
    if isinstance(settings, list):
        return settings[0] if settings else {}
    return settings if isinstance(settings, dict) else {}


def parse_settings(content: dict) -> dict:
    """Scalar league settings (playoff structure, keeper count, draft type)."""
    s = _settings_blob(content)
    return {
        "playoff_start_week": _num(s.get("playoff_start_week"), 0),
        "num_playoff_teams": _num(s.get("num_playoff_teams"), 0),
        "max_teams": _num(s.get("max_teams"), 0),
        "waiver_type": s.get("waiver_type"),
        "trade_end_date": s.get("trade_end_date"),
        "draft_type": s.get("draft_type"),
        "uses_playoff": bool(_num(s.get("uses_playoff"), 0)),
        "uses_faab": bool(_num(s.get("uses_faab"), 0)),
    }


def parse_stat_categories(content: dict) -> list[dict]:
    """Scoring categories. Nested as {"stat_categories": {"stats": [{"stat": {...}}]}}."""
    s = _settings_blob(content)
    container = s.get("stat_categories", {})
    if isinstance(container, list):
        container = container[0] if container else {}
    stats = container.get("stats", []) if isinstance(container, dict) else []
    if isinstance(stats, dict):
        stats = stats.get("stat", [])

    out = []
    for entry in _as_list(stats):
        stat = _unwrap(entry, "stat")
        if not stat:
            continue
        stat_id = str(stat.get("stat_id", ""))
        display_flag = stat.get("is_only_display_stat", "0")
        out.append({
            "stat_id": stat_id,
            "name": YAHOO_STAT_MAP.get(stat_id, stat.get("abbr") or stat_id),
            "display_name": stat.get("display_name") or stat.get("name") or stat_id,
            "sort_order": _num(stat.get("sort_order"), 0),
            "is_only_display": bool(_num(display_flag, 0)),
        })
    return out


def parse_roster_positions(content: dict) -> list[dict]:
    """Roster slots. Nested as [{"roster_position": {...}}, ...]."""
    s = _settings_blob(content)
    raw = s.get("roster_positions", [])
    if isinstance(raw, dict):
        raw = raw.get("roster_position", [])

    out = []
    for entry in _as_list(raw):
        rp = _unwrap(entry, "roster_position")
        if not rp or not rp.get("position"):
            continue
        out.append({
            "position": rp["position"],
            "position_type": rp.get("position_type"),
            "count": _num(rp.get("count"), 1),
        })
    return out


# --- Teams ---------------------------------------------------------------

def _parse_team(team_data: list) -> dict:
    """Yahoo team shape: [[{team_key}, {team_id}, {name}, ...], {team_standings}, ...]."""
    row = {
        "team_key": None, "team_id": None, "name": None, "manager_name": None,
        "wins": 0, "losses": 0, "ties": 0, "standing": None,
        "moves": 0, "trades": 0, "logo_url": None,
    }
    if not team_data:
        return row

    for item in _info_list(team_data):
        if "team_key" in item:
            row["team_key"] = item["team_key"]
        if "team_id" in item:
            row["team_id"] = str(item["team_id"])
        if "name" in item and isinstance(item["name"], str):
            row["name"] = item["name"]
        if "number_of_moves" in item:
            row["moves"] = _num(item["number_of_moves"], 0)
        if "number_of_trades" in item:
            row["trades"] = _num(item["number_of_trades"], 0)
        if "team_logos" in item:
            for logo in _as_list(item["team_logos"]):
                inner = _unwrap(logo, "team_logo")
                if inner and inner.get("url"):
                    row["logo_url"] = inner["url"]
                    break
        if "managers" in item:
            for mgr in _as_list(item["managers"]):
                inner = _unwrap(mgr, "manager")
                if inner and inner.get("nickname"):
                    row["manager_name"] = inner["nickname"]
                    break

    for elem in team_data[1:]:
        if not isinstance(elem, dict) or "team_standings" not in elem:
            continue
        standings = elem["team_standings"]
        if not isinstance(standings, dict):
            continue
        row["standing"] = _num(standings.get("rank"), 0) or None
        outcome = standings.get("outcome_totals", {})
        if isinstance(outcome, dict):
            row["wins"] = _num(outcome.get("wins"), 0)
            row["losses"] = _num(outcome.get("losses"), 0)
            row["ties"] = _num(outcome.get("ties"), 0)

    return row


def parse_standings(data: dict) -> list[dict]:
    """From /league/{league_key}/standings."""
    league = _as_list(data.get("fantasy_content", {}).get("league"))
    if len(league) < 2 or not isinstance(league[1], dict):
        return []

    standings = league[1].get("standings", {})
    if isinstance(standings, list):
        standings = standings[0] if standings else {}
    teams_raw = standings.get("teams", {}) if isinstance(standings, dict) else {}

    rows = []
    for team in _indexed(teams_raw):
        row = _parse_team(_as_list(team.get("team")))
        if row["team_key"] or row["team_id"]:
            rows.append(row)
    return rows


def parse_my_team_key(data: dict) -> str | None:
    """From /users;use_login=1/.../teams — which team belongs to the logged-in user."""
    users = data.get("fantasy_content", {}).get("users", {})
    for user in _indexed(users):
        for user_elem in _as_list(user.get("user")):
            if not isinstance(user_elem, dict) or "games" not in user_elem:
                continue
            for game in _indexed(user_elem["games"]):
                for game_elem in _as_list(game.get("game")):
                    if not isinstance(game_elem, dict) or "leagues" not in game_elem:
                        continue
                    for lg in _indexed(game_elem["leagues"]):
                        for lg_elem in _as_list(lg.get("league")):
                            if not isinstance(lg_elem, dict) or "teams" not in lg_elem:
                                continue
                            for team in _indexed(lg_elem["teams"]):
                                for item in _info_list(_as_list(team.get("team"))):
                                    if "team_key" in item:
                                        return item["team_key"]
    return None


# --- Players -------------------------------------------------------------

def parse_players(players_raw: dict) -> list[dict]:
    """
    From a roster or player-search response.

    Returns one row per player carrying both player attributes and the roster slot
    (`selected_position`), which the caller splits across the players/rosters tables.
    """
    rows = []
    for entry in _indexed(players_raw):
        player_data = _as_list(entry.get("player"))
        if not player_data:
            continue

        row = {
            "player_key": None, "player_id": None, "full_name": None,
            "first_name": None, "last_name": None, "editorial_team_abbr": None,
            "positions": [], "display_position": None, "status": None,
            "injury_note": None, "birth_date": None, "uniform_number": None,
            "percent_owned": None, "selected_position": None,
        }

        for item in _info_list(player_data):
            if "player_key" in item:
                row["player_key"] = item["player_key"]
            if "player_id" in item:
                row["player_id"] = str(item["player_id"])
            if "name" in item and isinstance(item["name"], dict):
                row["full_name"] = item["name"].get("full")
                row["first_name"] = item["name"].get("first")
                row["last_name"] = item["name"].get("last")
            if "editorial_team_abbr" in item:
                row["editorial_team_abbr"] = item["editorial_team_abbr"]
            if "display_position" in item:
                row["display_position"] = item["display_position"]
                row["positions"] = [p.strip() for p in item["display_position"].split(",") if p.strip()]
            if "eligible_positions" in item:
                eligible = []
                for pos in _as_list(item["eligible_positions"]):
                    if isinstance(pos, dict) and pos.get("position"):
                        eligible.append(pos["position"])
                    elif isinstance(pos, str):
                        eligible.append(pos)
                if eligible:
                    row["positions"] = eligible
            if "status_full" in item:
                row["injury_note"] = item["status_full"]
            if "status" in item:
                row["status"] = item["status"] or None
            if "injury_note" in item and item["injury_note"]:
                row["injury_note"] = item["injury_note"]
            if "birth_date" in item:
                row["birth_date"] = item["birth_date"]
            if "uniform_number" in item:
                row["uniform_number"] = str(item["uniform_number"])

        # selected_position and ownership live in later positional elements
        for elem in player_data[1:]:
            if not isinstance(elem, dict):
                continue
            if "selected_position" in elem:
                for sp in _as_list(elem["selected_position"]):
                    if isinstance(sp, dict) and sp.get("position"):
                        row["selected_position"] = sp["position"]
                        break
            if "percent_owned" in elem:
                po = elem["percent_owned"]
                if isinstance(po, list):
                    po = next((p for p in po if isinstance(p, dict) and "value" in p), {})
                if isinstance(po, dict) and po.get("value") is not None:
                    row["percent_owned"] = _num(po["value"], 0.0)

        if row["player_key"] or row["player_id"]:
            rows.append(row)
    return rows


def parse_player_stats(players_raw: dict, stat_period: str) -> list[dict]:
    """
    From /players;player_keys=...;out=stats;type=...

    Emits long format — one row per (player, period, stat) — so a league adding or
    changing scoring categories never requires a schema change.
    """
    rows = []
    for entry in _indexed(players_raw):
        player_data = _as_list(entry.get("player"))
        if not player_data:
            continue

        player_key = player_id = None
        for item in _info_list(player_data):
            if "player_key" in item:
                player_key = item["player_key"]
            if "player_id" in item:
                player_id = str(item["player_id"])
        if not (player_key or player_id):
            continue

        for elem in player_data[1:]:
            if not isinstance(elem, dict):
                continue
            player_stats = elem.get("player_stats")
            if not isinstance(player_stats, dict):
                continue
            stats = player_stats.get("stats", [])
            if isinstance(stats, dict):
                stats = stats.get("stat", [])
            for stat_entry in _as_list(stats):
                stat = _unwrap(stat_entry, "stat")
                if not stat:
                    continue
                stat_id = str(stat.get("stat_id", ""))
                raw_value = stat.get("value")
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    # Yahoo sends "-" for a stat with no data, and "12/25" for ratios.
                    value = None
                rows.append({
                    "player_key": player_key,
                    "player_id": player_id,
                    "stat_period": stat_period,
                    "stat_id": stat_id,
                    "stat_name": YAHOO_STAT_MAP.get(stat_id, stat_id),
                    "value": value,
                    "raw_value": None if raw_value is None else str(raw_value),
                })
    return rows
