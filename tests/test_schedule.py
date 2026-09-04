"""
Fixture mirrors the real shape of stats.nba.com's ScheduleLeagueV2 payload closely
enough to exercise the filtering: a preseason game, a normal game, a cup game, and a
knockout-round game whose matchup isn't decided yet (both teams null).
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy.sources.schedule import client, parse

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


def _team(tricode):
    return {"teamTricode": tricode} if tricode else {"teamTricode": None}


PAYLOAD = {"leagueSchedule": {"gameDates": [
    {"gameDate": "10/03/2026 00:00:00", "games": [
        {"gameId": "0012600009", "gameDateEst": "2026-10-03T00:00:00Z",
         "gameLabel": "Preseason", "isNeutral": False,
         "homeTeam": _team("POR"), "awayTeam": _team("LON")},
    ]},
    {"gameDate": "10/20/2026 00:00:00", "games": [
        {"gameId": "0022600001", "gameDateEst": "2026-10-20T00:00:00Z",
         "gameLabel": "", "isNeutral": False,
         "homeTeam": _team("DET"), "awayTeam": _team("BOS")},
        {"gameId": "0022600061", "gameDateEst": "2026-10-30T00:00:00Z",
         "gameLabel": "Emirates NBA Cup", "isNeutral": False,
         "homeTeam": _team("BOS"), "awayTeam": _team("CHI")},
    ]},
    {"gameDate": "12/04/2026 00:00:00", "games": [
        {"gameId": "0012600009", "gameDateEst": "2026-12-04T00:00:00Z",
         "gameLabel": "Emirates NBA Cup", "isNeutral": False,
         "homeTeam": _team(None), "awayTeam": _team(None)},
    ]},
]}}

rows = parse.parse_schedule(PAYLOAD)

check("preseason and TBD-matchup games dropped", len(rows), 2)
check("first row is the regular game", rows[0]["game_id"], "0022600001")
check("date sliced to YYYY-MM-DD", rows[0]["game_date"], "2026-10-20")
check("teams are tricodes", (rows[0]["home_team"], rows[0]["away_team"]), ("DET", "BOS"))
check("normal game label is NULL", rows[0]["game_label"], None)
check("cup label preserved", rows[1]["game_label"], "Emirates NBA Cup")

check("empty payload", parse.parse_schedule({}), [])
check("missing gameDates", parse.parse_schedule({"leagueSchedule": {}}), [])

# --- season inference: NBA labels a season by its starting year, rolling over Aug 1 ---
check("mid-season date", client.current_season(date(2026, 1, 15)), "2025-26")
check("just before rollover", client.current_season(date(2026, 7, 31)), "2025-26")
check("on rollover day", client.current_season(date(2026, 8, 1)), "2026-27")
check("after opening night", client.current_season(date(2026, 11, 1)), "2026-27")

if failures:
    print(f"FAILED ({len(failures)}):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all schedule checks passed")
