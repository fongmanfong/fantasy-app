"""Pure parser for the ScheduleLeagueV2 payload. No I/O, no database."""

# ScheduleLeagueV2 already returns Yahoo-style tricodes (TOR, GSW, LAC, ...),
# so games join straight onto players.editorial_team_abbr with no lookup table.

# Non-regular-season entries this endpoint mixes in: exhibitions before opening
# night, and (once assigned) preseason opponents outside the 30 NBA teams.
_EXCLUDED_LABELS = {"Preseason"}


def parse_schedule(payload: dict) -> list[dict]:
    """
    One row per game. Skips preseason, and skips games whose matchup isn't
    decided yet — the Emirates NBA Cup semifinals and final are entered with a
    real date but a null team on both sides until the group stage finishes.
    """
    rows = []
    for day in payload.get("leagueSchedule", {}).get("gameDates", []):
        for game in day.get("games", []):
            if game.get("gameLabel") in _EXCLUDED_LABELS:
                continue

            home = game.get("homeTeam", {}).get("teamTricode")
            away = game.get("awayTeam", {}).get("teamTricode")
            if not home or not away:
                continue

            game_date_est = game.get("gameDateEst")
            if not game_date_est:
                continue

            rows.append({
                "game_id": game.get("gameId"),
                "game_date": game_date_est[:10],
                "home_team": home,
                "away_team": away,
                "game_label": game.get("gameLabel") or None,
                "is_neutral_site": bool(game.get("isNeutral")),
            })
    return rows
