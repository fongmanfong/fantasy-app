"""
Fixture mirrors the shape of stats.nba.com's LeagueDashPlayerStats payload: the real
header order with its *_RANK twins present, a traded player carrying TEAM_COUNT 2,
and a row missing its player id. No network, no database.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy import history
from fantasy.sources.history import client, parse

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


HEADERS = ["PLAYER_ID", "PLAYER_NAME", "NICKNAME", "TEAM_ID", "TEAM_ABBREVIATION",
           "AGE", "GP", "W", "L", "W_PCT", "MIN", "FGM", "FGA", "FG_PCT", "FG3M",
           "FG3A", "FG3_PCT", "FTM", "FTA", "FT_PCT", "OREB", "DREB", "REB", "AST",
           "TOV", "STL", "BLK", "BLKA", "PF", "PFD", "PTS", "PLUS_MINUS",
           "NBA_FANTASY_PTS", "DD2", "TD3", "PTS_RANK", "TEAM_COUNT"]


def _row(player_id, name, team, team_count, **over):
    values = {"AGE": 26.0, "GP": 70, "MIN": 2400.0, "FGM": 500, "FGA": 1100,
              "FG_PCT": 0.455, "FG3M": 150, "FG3A": 400, "FG3_PCT": 0.375,
              "FTM": 300, "FTA": 350, "FT_PCT": 0.857, "OREB": 50, "DREB": 300,
              "REB": 350, "AST": 500, "TOV": 200, "STL": 80, "BLK": 30,
              "PTS": 1450, "DD2": 20, "TD3": 3, "NBA_FANTASY_PTS": 3000.0,
              "PF": 150, "PTS_RANK": 12}
    values.update(over)
    values.update({"PLAYER_ID": player_id, "PLAYER_NAME": name, "NICKNAME": name.split()[0],
                   "TEAM_ID": 1610612737, "TEAM_ABBREVIATION": team,
                   "TEAM_COUNT": team_count, "W": 40, "L": 30, "W_PCT": 0.571,
                   "BLKA": 40, "PFD": 160, "PLUS_MINUS": 100})
    return [values.get(h) for h in HEADERS]


PAYLOAD = {"resultSets": [{
    "name": "LeagueDashPlayerStats",
    "headers": HEADERS,
    "rowSet": [
        _row(1629027, "Trae Young", "ATL", 1),
        _row(1629029, "Luka Dončić", "LAL", 2, GP=50, PTS=1408),
        _row(None, "Nobody At All", "ATL", 1),
    ],
}]}

rows = parse.parse_player_seasons(PAYLOAD)

check("row with no player id dropped", len(rows), 2)
check("nba player id kept", rows[0]["player_id"], 1629027)
check("accents preserved verbatim", rows[1]["player_name"], "Luka Dončić")
check("totals, not per game", rows[0]["pts"], 1450)
check("MIN renamed to minutes", rows[0]["minutes"], 2400.0)
check("threes made kept as fg3m", rows[0]["fg3m"], 150)
check("trade shows in team_count", rows[1]["team_count"], 2)
check("rank columns dropped", [k for k in rows[0] if k.endswith("_rank")], [])
check("win/loss columns dropped", [k for k in rows[0] if k in ("w", "l", "w_pct")], [])

check("other result sets ignored",
      parse.parse_player_seasons({"resultSets": [{"name": "SomethingElse",
                                                  "headers": [], "rowSet": []}]}), [])
check("empty payload", parse.parse_player_seasons({}), [])
check("missing rowSet", parse.parse_player_seasons(
    {"resultSets": [{"name": "LeagueDashPlayerStats", "headers": HEADERS}]}), [])

# --- which seasons to ask for: the ones that have actually been played ---
check("august: current season labelled but unplayed",
      client.recent_seasons(4, date(2026, 8, 15)),
      ["2022-23", "2023-24", "2024-25", "2025-26"])
check("september: same",
      client.recent_seasons(4, date(2026, 9, 5)),
      ["2022-23", "2023-24", "2024-25", "2025-26"])
check("november: current season is under way and included",
      client.recent_seasons(4, date(2026, 11, 1)),
      ["2023-24", "2024-25", "2025-26", "2026-27"])
check("mid-season", client.recent_seasons(2, date(2026, 1, 15)),
      ["2024-25", "2025-26"])
check("july: season over, still the newest played",
      client.recent_seasons(1, date(2026, 7, 31)), ["2025-26"])

# --- which seasons are worth a request: a finished season never changes ---
STORED = {"2022-23", "2023-24", "2024-25"}
IN_PROGRESS = "2026-27"


def should(season, refresh=False):
    return history.should_pull(season, STORED, IN_PROGRESS, refresh)


check("a stored, finished season is skipped", should("2023-24"), False)
check("a missing season is fetched", should("2025-26"), True)
check("--refresh re-fetches a stored season", should("2023-24", refresh=True), True)

# The one season whose totals are still moving. Stored or not, a copy of it is a
# snapshot of a number that has since gone up.
check("the season in progress is always re-fetched", should(IN_PROGRESS), True)
STORED_WITH_CURRENT = STORED | {IN_PROGRESS}
check("...even when it is already stored",
      history.should_pull(IN_PROGRESS, STORED_WITH_CURRENT, IN_PROGRESS), True)

check("nothing stored yet: everything is fetched",
      [s for s in client.recent_seasons(4, date(2026, 9, 5))
       if history.should_pull(s, set(), IN_PROGRESS)],
      ["2022-23", "2023-24", "2024-25", "2025-26"])
check("a year missed: only the gap is fetched",
      [s for s in client.recent_seasons(4, date(2026, 9, 5))
       if history.should_pull(s, STORED, IN_PROGRESS)],
      ["2025-26"])

if failures:
    print(f"FAILED ({len(failures)}):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all history checks passed")
