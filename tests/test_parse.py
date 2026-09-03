"""
Fixtures mirror Yahoo's real response shapes: positional arrays, index-keyed maps
with a "count" sibling, and single-element containers that arrive as either a dict
or a 1-item list.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy.yahoo import parse

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


# --- my leagues ---
MY_LEAGUES = {"fantasy_content": {"users": {"count": 1, "0": {"user": [
    {"guid": "ABC"},
    {"games": {"count": 1, "0": {"game": [
        {"game_key": "466", "code": "nba", "season": "2025"},
        {"leagues": {"count": 1, "0": {"league": [{
            "league_key": "466.l.28641", "league_id": "28641",
            "name": "Lean Green Money-Makin Machine", "season": "2025",
            "num_teams": 12, "scoring_type": "head",
        }]}}},
    ]}}},
]}}}}

leagues = parse.parse_my_leagues(MY_LEAGUES)
check("my_leagues count", len(leagues), 1)
check("league_key is Yahoo's own", leagues[0]["league_key"], "466.l.28641")
check("game_key captured", leagues[0]["game_key"], "466")
check("season coerced to int", leagues[0]["season"], 2025)

# --- settings: stat_categories nested under a 1-item list ---
SETTINGS = {"league": [
    {"league_key": "466.l.28641", "league_id": "28641", "name": "LGMM",
     "season": "2025", "num_teams": 12, "current_week": "3",
     "scoring_type": "head", "is_finished": 0},
    {"settings": [{
        "playoff_start_week": "20", "num_playoff_teams": "6", "uses_faab": "1",
        "stat_categories": {"stats": [
            {"stat": {"stat_id": 12, "name": "Points Scored", "display_name": "PTS",
                      "sort_order": "1", "is_only_display_stat": "0"}},
            {"stat": {"stat_id": 4, "name": "Field Goals Attempted", "display_name": "FGA",
                      "sort_order": "1", "is_only_display_stat": "1"}},
        ]},
        "roster_positions": [
            {"roster_position": {"position": "PG", "position_type": "P", "count": 1}},
            {"roster_position": {"position": "BN", "count": 3}},
        ],
    }]},
]}

check("league name", parse.parse_league(SETTINGS)["name"], "LGMM")
check("current_week int", parse.parse_league(SETTINGS)["current_week"], 3)
check("is_finished bool", parse.parse_league(SETTINGS)["is_finished"], False)

cats = parse.parse_stat_categories(SETTINGS)
check("stat cat count", len(cats), 2)
check("stat id 12 maps to PTS", cats[0]["name"], "PTS")
check("is_only_display parsed", [c["is_only_display"] for c in cats], [False, True])

pos = parse.parse_roster_positions(SETTINGS)
check("roster positions", [(p["position"], p["count"]) for p in pos], [("PG", 1), ("BN", 3)])
check("settings faab", parse.parse_settings(SETTINGS)["uses_faab"], True)

# --- standings ---
STANDINGS = {"fantasy_content": {"league": [
    {"league_key": "466.l.28641"},
    {"standings": [{"teams": {"count": 2,
        "0": {"team": [
            [{"team_key": "466.l.28641.t.4"}, {"team_id": 4},
             {"name": "Red Eyes Black Dragon"}, [],
             {"managers": [{"manager": {"nickname": "Jason"}}]}],
            {"team_standings": {"rank": 2, "outcome_totals": {"wins": "10", "losses": "5", "ties": "0"}}},
        ]},
        "1": {"team": [
            [{"team_key": "466.l.28641.t.7"}, {"team_id": 7}, {"name": "Other Guys"}],
            {"team_standings": {"rank": 5, "outcome_totals": {"wins": 7, "losses": 8, "ties": 0}}},
        ]},
    }}]},
]}}

teams = parse.parse_standings(STANDINGS)
check("teams parsed", len(teams), 2)
check("team_key", teams[0]["team_key"], "466.l.28641.t.4")
check("team name past empty array", teams[0]["name"], "Red Eyes Black Dragon")
check("manager nickname", teams[0]["manager_name"], "Jason")
check("wins coerced from str", teams[0]["wins"], 10)
check("standing", teams[1]["standing"], 5)

# --- my team key ---
MY_TEAM = {"fantasy_content": {"users": {"count": 1, "0": {"user": [
    {"guid": "ABC"},
    {"games": {"0": {"game": [
        {"game_key": "466"},
        {"leagues": {"0": {"league": [
            {"league_key": "466.l.28641"},
            {"teams": {"count": 1, "0": {"team": [
                [{"team_key": "466.l.28641.t.4"}, {"team_id": 4}, {"name": "Red Eyes Black Dragon"}]
            ]}}},
        ]}}},
    ]}}},
]}}}}
check("my team key", parse.parse_my_team_key(MY_TEAM), "466.l.28641.t.4")

# --- players ---
PLAYERS = {"count": 2,
  "0": {"player": [
      [{"player_key": "466.p.6014"}, {"player_id": 6014},
       {"name": {"full": "Nikola Jokic", "first": "Nikola", "last": "Jokic"}},
       {"editorial_team_abbr": "DEN"}, {"uniform_number": "15"},
       {"display_position": "C"},
       {"eligible_positions": [{"position": "C"}, {"position": "Util"}]},
       {"status": "GTD"}, {"status_full": "Game Time Decision"},
       {"birth_date": "1995-02-19"}],
      {"selected_position": [{"coverage_type": "date"}, {"position": "C"}]},
  ]},
  "1": {"player": [
      [{"player_key": "466.p.9999"}, {"player_id": 9999},
       {"name": {"full": "Bench Guy"}}, {"display_position": "PG,SG"}],
      {"percent_owned": [{"coverage_type": "week"}, {"value": 42}]},
  ]},
}

players = parse.parse_players(PLAYERS)
check("player count", len(players), 2)
check("full name", players[0]["full_name"], "Nikola Jokic")
check("eligible_positions win over display_position", players[0]["positions"], ["C", "Util"])
check("selected_position from later element", players[0]["selected_position"], "C")
check("injury note", players[0]["injury_note"], "Game Time Decision")
check("birth_date", players[0]["birth_date"], "1995-02-19")
check("display_position split", players[1]["positions"], ["PG", "SG"])
check("percent_owned", players[1]["percent_owned"], 42.0)
check("no selected_position", players[1]["selected_position"], None)

# --- stats, including Yahoo's "-" for no data ---
STATS = {"count": 1, "0": {"player": [
    [{"player_key": "466.p.6014"}, {"player_id": 6014}, {"name": {"full": "Nikola Jokic"}}],
    {"player_stats": {"0": {"coverage_type": "season"}, "stats": [
        {"stat": {"stat_id": "12", "value": "29.6"}},
        {"stat": {"stat_id": "5", "value": ".576"}},
        {"stat": {"stat_id": "24", "value": "-"}},
    ]}},
]}}

stats = parse.parse_player_stats(STATS, "season")
check("stat rows", len(stats), 3)
check("PTS named", (stats[0]["stat_name"], stats[0]["value"]), ("PTS", 29.6))
check("FG% named", stats[1]["stat_name"], "FG%")
check("dash becomes NULL", stats[2]["value"], None)
check("raw preserved", stats[2]["raw_value"], "-")
check("period stamped", {s["stat_period"] for s in stats}, {"season"})

# --- empty / malformed input must not raise ---
check("empty leagues", parse.parse_my_leagues({}), [])
check("empty standings", parse.parse_standings({}), [])
check("empty players", parse.parse_players({}), [])
check("empty stats", parse.parse_player_stats({}, "season"), [])
check("no team key", parse.parse_my_team_key({}), None)

if failures:
    print(f"FAILED ({len(failures)}):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all parser checks passed")
