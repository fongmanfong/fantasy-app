"""Pure parser for the LeagueDashPlayerStats payload. No I/O, no database."""

# nba.com header -> our column. Everything not named here is dropped: the payload
# carries a *_RANK twin for every stat, plus W/L records and WNBA fantasy points,
# none of which say anything a fantasy read of the row needs.
_COLUMNS = {
    "PLAYER_ID": "player_id",
    "PLAYER_NAME": "player_name",
    "TEAM_ABBREVIATION": "team_abbr",
    "TEAM_COUNT": "team_count",
    "AGE": "age",
    "GP": "gp",
    "MIN": "minutes",   # renamed: `min` would shadow the SQL function
    "FGM": "fgm",
    "FGA": "fga",
    "FG_PCT": "fg_pct",
    "FG3M": "fg3m",
    "FG3A": "fg3a",
    "FG3_PCT": "fg3_pct",
    "FTM": "ftm",
    "FTA": "fta",
    "FT_PCT": "ft_pct",
    "OREB": "oreb",
    "DREB": "dreb",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "TOV": "tov",
    "PF": "pf",
    "PTS": "pts",
    "DD2": "dd2",
    "TD3": "td3",
    "NBA_FANTASY_PTS": "fantasy_pts",
}


def parse_player_seasons(payload: dict) -> list[dict]:
    """
    One row per player for the season the payload was fetched for.

    A player traded mid-season gets a single row whose totals cover every team
    he played for; `team_abbr` is then the last of them and `team_count` says
    how many there were. Nothing here knows which season this is — the caller
    stamps it, the same way `nba_schedule` rows are stamped.
    """
    for result in payload.get("resultSets", []):
        if result.get("name") != "LeagueDashPlayerStats":
            continue

        headers = result.get("headers") or []
        index = {h: i for i, h in enumerate(headers)}
        rows = []
        for raw in result.get("rowSet") or []:
            row = {col: raw[index[header]]
                   for header, col in _COLUMNS.items() if header in index}
            if row.get("player_id") is None:
                continue
            rows.append(row)
        return rows
    return []
