"""
The composite ranking — the folding rule, and the round trip through DuckDB.

Everything here runs against an in-memory database built from the real
schema.sql, so the storage half of the test is checking the actual tables and
views rather than a stand-in. No network, no database file.

The fixture is three sources of deliberately different depth, because depth is
what the interesting cases are about: a source too short to have an opinion, a
source long enough to have left someone off on purpose, a hole in a source's
own numbering, and a draft pick sitting among the players.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from fantasy.analysis import composite
from fantasy.store import db

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


def close(label, actual, expected, tol=1e-9):
    if actual is None or abs(actual - expected) > tol:
        failures.append(f"{label}\n    expected: {expected!r} (±{tol})\n    actual:   {actual!r}")


def raises(label, fn, fragment=""):
    try:
        fn()
    except Exception as exc:
        if fragment and fragment not in str(exc):
            failures.append(f"{label}\n    expected message containing {fragment!r}"
                            f"\n    actual:   {exc}")
        return
    failures.append(f"{label}\n    expected an exception, got none")


# --- the curve ----------------------------------------------------------

check("the top of a list is worth the full 100", composite.value(1), 100.0)
check("value falls with rank", composite.value(50) < composite.value(10), True)
check("a longer curve is worth more at the same rank",
      composite.value(50, curve=200) > composite.value(50, curve=40), True)


# --- a fixture with the four cases in it --------------------------------

# hashtag ranks 8 deep, angle 5, dynatyze 3 — and dynatyze's #2 is missing from
# its numbering, which is the hole the inference is for.
ROWS = {
    "hashtag_dynasty": [
        (1, "Ace Best"), (2, "Bo Second"), (3, "Cy Third"), (4, "Dee Fourth"),
        (5, "Eli Fifth"), (6, "Fay Sixth"), (7, "Gus Seventh"), (8, "Hal Eighth"),
    ],
    "angle_dynasty": [
        (1, "Ace Best"), (2, "Cy Third"), (3, "Bo Second"), (4, "Dee Fourth"),
        (5, "Eli Fifth"),
    ],
    # rank 2 has no row: a hole. rank 3 is a pick, which holds its slot.
    "dynatyze_dynasty": [(1, "Ace Best"), (3, "2027 Early 1st")],
}


def fixture():
    con = duckdb.connect()
    db.init_schema(con)
    for i, (source, rows) in enumerate(ROWS.items(), 1):
        con.execute(
            "INSERT INTO ranking_pulls VALUES (?, ?, 'http://x', now(), 'success', null)",
            [i, source])
        for rank, name in rows:
            con.execute(
                "INSERT INTO player_rankings (ranking_pull_id, source, rank, "
                "player_name, player_name_key) VALUES (?, ?, ?, ?, lower(?))",
                [i, source, rank, name, name])
    return con


con = fixture()
built = composite.build(con)
players = {p["player_name_key"]: p for p in built["players"]}

check("every ranked name is reranked, and only those", len(built["players"]), 8)
check("the sources found are the ones stored",
      sorted(built["sources"]), ["angle_dynasty", "dynatyze_dynasty", "hashtag_dynasty"])
check("each source's depth is its deepest rank, pick included",
      built["depth"], {"hashtag_dynasty": 8, "angle_dynasty": 5, "dynatyze_dynasty": 3})

check("a draft pick is held out of the players",
      any(p["player_name"].startswith("2027") for p in built["players"]), False)
check("but is reported", [p["player_name"] for p in built["picks"]], ["2027 Early 1st"])
check("and keeps its slot, so only the real hole is hidden",
      built["hidden"], {"dynatyze_dynasty": [2]})

ace = players["ace best"]
check("unanimous #1 comes first", ace["rank"], 1)
close("and scores the full 100", ace["score"], 100.0)
check("with no spread", ace["spread"], 0)

# Bo is #2 and #3 on the deep lists, so dynatyze's 3-deep list saw him.
bo = players["bo second"]
check("a source deep enough to have seen a player votes on him",
      bo["votes"]["dynatyze_dynasty"]["kind"], "inferred")
check("and here the vote is its empty slot, not a penalty",
      bo["votes"]["dynatyze_dynasty"]["effective"], 2.0)
check("consensus ignores the inferred vote", round(bo["consensus"], 4),
      round((2 * 3) ** 0.5, 4))

# Cy is the other claimant on that slot but ranks worse than Bo, so he is
# the one left carrying dynatyze's list-end penalty.
cy = players["cy third"]
check("only as many slots as exist are inferred",
      cy["votes"]["dynatyze_dynasty"]["kind"], "passed")
close("a passed vote sits just past the list's end",
      cy["votes"]["dynatyze_dynasty"]["effective"], 3 * composite.DEFAULT_CENSOR)

# Fay is 6th on the 8-deep list and beyond the reach of the other two.
fay = players["fay sixth"]
check("a list too short to reach a player casts no vote",
      sorted(fay["votes"]), ["hashtag_dynasty"])
check("which is visible as fewer votes than sources", (fay["n_sources"], fay["n_votes"]), (1, 1))
check("while a player every source saw has a vote from each",
      (bo["n_sources"], bo["n_votes"]), (2, 3))

check("the order runs by score", [p["player_name"] for p in built["players"]][:4],
      ["Ace Best", "Bo Second", "Cy Third", "Dee Fourth"])
check("spread is the widest disagreement among sources that ranked him",
      cy["spread"], 1)
check("and is None when only one source ranked him", fay["spread"], None)

raises("an unknown kind is refused rather than returning nothing",
       lambda: composite.build(con, kind="redraft"), "No redraft rankings stored")


# --- the round trip through the store -----------------------------------

raises("reading before any run says so, rather than returning empty",
       lambda: composite.load(con), "No stored dynasty composite")

run_id = db.new_composite_run(con, "dynasty", built["sources"], built["params"])
db.insert_composite_rows(con, [
    {**{k: p[k] for k in ("rank", "score", "player_name", "player_name_key",
                          "player_key", "team_abbr", "age", "n_sources",
                          "n_votes", "consensus", "spread")},
     "votes": json.dumps(p["votes"])}
    for p in built["players"]], run_id)

check("a run in flight is not readable yet",
      con.execute("SELECT count(*) FROM v_composite_rankings").fetchone()[0], 0)

db.complete_composite_run(con, run_id, "success", "note")
check("and is once it closes",
      con.execute("SELECT count(*) FROM v_composite_rankings").fetchone()[0], 8)

stored = composite.load(con)
check("the stored order is the computed one",
      [p["player_name"] for p in stored["players"]],
      [p["player_name"] for p in built["players"]])
check("the parameters come back with it", stored["params"], built["params"])
check("so do the pulls it was built from", stored["sources"], built["sources"])
check("and each source's vote survives the round trip",
      stored["players"][1]["votes"]["dynatyze_dynasty"]["kind"], "inferred")

# A second run must not disturb the first: the store is append-only.
second = db.new_composite_run(con, "dynasty", built["sources"], built["params"])
db.insert_composite_rows(con, [{"rank": 1, "score": 1.0, "player_name": "Only Player",
                                "player_name_key": "only player", "votes": "{}"}], second)
db.complete_composite_run(con, second, "success", None)
check("the newest successful run is what the view resolves to",
      [p["player_name"] for p in composite.load(con)["players"]], ["Only Player"])
check("but the earlier run is still there to read by id",
      con.execute("SELECT count(*) FROM composite_rankings WHERE run_id = ?",
                  [run_id]).fetchone()[0], 8)

con.close()

if failures:
    print(f"FAILED ({len(failures)}):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all composite checks passed")
