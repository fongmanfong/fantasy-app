"""
The LineupExperts parser, with no network.

Fixture mirrors the real CSV export (see fantasy/sources/rankings/lineupexperts.py):
a byte-order mark, quoted cells, and a Player cell that packs name, team and
positions apart with a run of padding. Team codes are ESPN's, one player has no
team, and one cell does not split the usual way.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy import rankings
from fantasy.sources.rankings.lineupexperts import parse_dynasty

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


PAD = " " * 120
CSV = (
    "﻿\"Rank\",\"Player\",\"Age\"\n"
    f"\"1\",\"Victor Wembanyama{PAD}SA - C\",\"22\"\n"
    f"\"4\",\"Jayson Tatum{PAD}BOS - PF,SF\",\"28\"\n"
    f"\"7\",\"Karl-Anthony Towns{PAD}NY - C,PF\",\"30\"\n"
    f"\"246\",\"Rob Dillingham{PAD}N/A - PG\",\"21\"\n"
    "\"300\",\"Somebody   Unsplit\",\"\"\n"
)

rows = parse_dynasty(CSV)
check("every ranked row parsed", len(rows), 5)

wemby = rows[0]
check("rank", wemby["rank"], 1)
check("name is everything before the padding", wemby["player_name"], "Victor Wembanyama")
check("ESPN team code rewritten to the NBA's", wemby["team_abbr"], "SAS")
check("positions", wemby["positions"], ["C"])
check("age", wemby["age"], 22.0)
check("extra", wemby["extra"], {})

check("a code shared by ESPN and the NBA is kept", rows[1]["team_abbr"], "BOS")
check("multiple positions split", rows[1]["positions"], ["PF", "SF"])
check("hyphenated name survives", rows[2]["player_name"], "Karl-Anthony Towns")
check("NY -> NYK", rows[2]["team_abbr"], "NYK")
check("N/A team becomes None", rows[3]["team_abbr"], None)

odd = rows[4]
check("an unsplittable cell keeps its whole text as the name",
      (odd["player_name"], odd["team_abbr"], odd["positions"], odd["age"]),
      ("Somebody Unsplit", None, [], None))

check("a file without the expected columns yields no rows",
      parse_dynasty("name,score\nfoo,1\n"), [])

# A from_file source refuses before opening the database, so this needs no file.
try:
    rankings.run("lineupexperts_dynasty")
    failures.append("pull without --file should have raised")
except RuntimeError as exc:
    check("refusal says to pass --file", "--file" in str(exc), True)

if failures:
    print(f"{len(failures)} FAILURE(S):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all lineupexperts checks passed")
