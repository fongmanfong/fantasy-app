"""
The report's formatting and derivations, with no database and no network.

`render_markdown` is a pure function of a dict, so the document is built here
from a hand-written fixture rather than a snapshot. The derivations that decide
what the report *says* — rank arithmetic, the staleness verdict, which players
to research — are each pure too, and are checked directly.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb

from fantasy import report
from fantasy.analysis.projection import Player

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


def raises(label, fn, fragment=""):
    try:
        fn()
    except Exception as exc:
        if fragment and fragment not in str(exc):
            failures.append(f"{label}\n    expected message containing {fragment!r}"
                            f"\n    actual:   {exc}")
        return
    failures.append(f"{label}\n    expected an exception, got none")


# --- cells and tables ---------------------------------------------------

check("a missing value renders as an em dash, never None", report._cell(None), "—")
check("counting stats keep one decimal", report._cell(218.264), "218.3")
check("large counting stats are grouped", report._cell(1234.5), "1,234.5")
check("rates drop the leading zero", report._cell(0.4731, rate=True), ".473")
check("percentages", report._pct(0.317), "31.7%")
check("a missing percentage is an em dash", report._pct(None), "—")
check("deltas keep their sign", report._signed(0.33), "+0.33")
check("negative deltas keep theirs", report._signed(-0.05), "-0.05")
check("suffixes attach", report._signed(8.1, 1, "pp"), "+8.1pp")

check("a record renders", report._record({"wins": 90, "losses": 87, "ties": 3}),
      "90-87-3")
check("a team with no standings gets an em dash, not None-None-None",
      report._record({}), "—")
check("a partial record fills the gap with zero",
      report._record({"wins": 5, "losses": None, "ties": None}), "5-0-0")

table = report._table(["A", "B"], [["x", 1]], "lr")
check("header row", table[0], "| A | B |")
check("alignment row follows the spec", table[1], "|---|---:|")
check("body row", table[2], "| x | 1 |")

check("a pipe in a cell is escaped, not left to break the table",
      report._table(["A"], [["a|b"]])[2], "| a\\|b |")
raises("a ragged row is a bug, not something to pad",
       lambda: report._table(["A", "B"], [["only one"]]), "expected 2")


# --- YAML front matter --------------------------------------------------

check("apostrophes survive unescaped inside double quotes",
      report._yaml_str("KD's Burner Team"), '"KD\'s Burner Team"')
check("a colon-space would break a bare scalar, so everything is quoted",
      report._yaml_str("Team: The Sequel"), '"Team: The Sequel"')
check("double quotes are escaped", report._yaml_str('say "hi"'), '"say \\"hi\\""')
check("backslashes are escaped", report._yaml_str("a\\b"), '"a\\\\b"')
check("booleans are YAML booleans, not strings", report._yaml_str(True), "true")
check("numbers stay bare", report._yaml_str(12), "12")
check("None is null", report._yaml_str(None), "null")

block = report._yaml_block({"a": 1, "b": {"c": "x"}, "d": [1, 2], "e": []})
check("nesting indents", block, ["a: 1", "b:", '  c: "x"', "d:", "  - 1", "  - 2", "e: []"])


# --- category profile ---------------------------------------------------

CATS = [{"key": "pts", "label": "PTS"},
        {"key": "tov", "label": "TO", "neg": True},
        {"key": "fg", "label": "FG%", "rate": True}]


def team(key, pts, tov, fg, mine=False):
    return {"team_key": key, "name": key, "is_my_team": mine, "mean_rank": 2.0,
            "totals": {"pts": pts, "tov": tov, "fg": fg}, "ranks": {}}


STANDINGS = {"teams": [team("me", 100.0, 20.0, 0.45, mine=True),
                       team("b", 120.0, 15.0, 0.50),
                       team("c", 110.0, 25.0, 0.40)]}

prof = {r["key"]: r for r in report._category_profile(
    STANDINGS, "me", {"pts": 0.4}, CATS)}

check("rank counts better teams above me", prof["pts"]["rank"], 3)
check("the field size is reported", prof["pts"]["teams"], 3)
check("gap to the next rank up is the distance worth closing",
      round(prof["pts"]["gap_to_next"], 1), 10.0)
check("a negative category ranks low-is-best", prof["tov"]["rank"], 2)
check("and its gap points at the better (lower) value",
      round(prof["tov"]["gap_to_next"], 1), 5.0)
check("the best value respects the category's direction", prof["tov"]["best"], 15.0)
check("steals and blocks are the flagged noisy pair", report.NOISY, {"stl", "blk"})
check("win probabilities are carried through when supplied",
      prof["pts"]["p_win"], 0.4)
check("and are None when they are not", prof["fg"]["p_win"], None)

eight = report._category_profile(STANDINGS, "me", {}, CATS[:2])
check("the league's category list governs, not the standings' nine",
      len(eight), 2)

# A team missing from a category must not crash the ranking.
partial = {"teams": STANDINGS["teams"] + [team("d", None, 1.0, 0.9)]}
check("a team with no value in a category is skipped, not ranked",
      report._category_profile(partial, "me", {}, CATS)[0]["teams"], 3)


# --- data quality -------------------------------------------------------

def quality(**kw):
    args = {"meta": {}, "cal": {"in_playoffs": False, "current_week": 5,
                                "playoff_start_week": 21, "games_per_week": 3.5},
            "pull_age_days": 0.5, "n_periods": 4, "identical_windows": False,
            "fa_total": 400, "fa_usable": 300,
            "settings": {"num_playoff_teams": 4, "waiver_type": "FR", "uses_faab": False}}
    args.update(kw)
    return {c["code"] for c in report._data_quality(**args)}


fresh = quality()
check("a fresh live snapshot is not called complete", "season_complete" in fresh, False)
check("truncation is not claimed when the pool is whole",
      "fa_pool_truncated" in fresh, False)
check("the caveats that always apply are always there",
      {"no_scoreboard", "no_schedule", "not_backtested"} <= fresh, True)

# The regression that matters: a two-day-old pull of a finished season is stale,
# and reporting it as fresh would be exactly backwards.
stale = quality(cal={"in_playoffs": True, "current_week": 23,
                     "playoff_start_week": 21, "games_per_week": 3.5},
                pull_age_days=2.0)
check("a recent pull of a finished season is flagged complete",
      "season_complete" in stale, True)

check("identical windows are called out",
      "identical_stat_windows" in quality(identical_windows=True), True)
check("a truncated pool is called out",
      "fa_pool_truncated" in quality(fa_total=25, fa_usable=16), True)
check("missing settings are called out",
      "settings_incomplete" in quality(settings={"num_playoff_teams": None,
                                                 "waiver_type": None,
                                                 "uses_faab": None}), True)

sev = {c["code"]: c["severity"] for c in report._data_quality(
    meta={}, cal={"in_playoffs": True, "current_week": 23, "playoff_start_week": 21,
                  "games_per_week": 3.5},
    pull_age_days=2.0, n_periods=4, identical_windows=True, fa_total=25,
    fa_usable=16, settings={})}
check("a finished season blocks", sev["season_complete"], "blocking")
check("every caveat carries a severity", all(sev.values()), True)


# --- research targets ---------------------------------------------------

def rp(key, name, pos, status="Healthy"):
    return {"player_key": key, "name": name, "pos": pos, "status": status, "nba": "LAL"}


def proj(key, n_eff, p_play):
    return Player(player_key=key, name=key, team_key="t", nba="LAL", status="Healthy",
                  positions=["C"], selected_position="BN", is_free_agent=False,
                  gp=n_eff, n_eff=n_eff, p_play=p_play, rates={}, fg_pct=None, ft_pct=None)


ROSTER = [rp("a", "Sure Thing", "PG"), rp("b", "Injured", "BN", "GTD"),
          rp("c", "Stashed", "IL"), rp("d", "Thin Sample", "BN")]
PROJECTED = {"a": proj("a", 70, 0.88), "b": proj("b", 60, 0.65),
             "c": proj("c", 60, 0.0), "d": proj("d", 9, 0.8)}
MOVES = [{"delta_cats": 0.3, "add": {"name": "Good Add"}, "drop": {"name": "X"}},
         {"delta_cats": -0.2, "add": {"name": "Bad Add"}, "drop": {"name": "Y"}}]

res = report._research_targets(ROSTER, PROJECTED, MOVES, list(prof.values()))
names = [p["name"] for p in res["uncertain_players"]]
check("a well-sampled healthy player is not worth researching",
      "Sure Thing" in names, False)
check("an IL player is the first place news would matter", names[0], "Stashed")
check("the injured and the thin-sampled are both flagged",
      {"Injured", "Thin Sample"} <= set(names), True)
check("only improving adds are put up for verification",
      [m["add"]["name"] for m in res["adds_to_verify"]], ["Good Add"])
check("the research list is stable across calls",
      report._research_targets(ROSTER, PROJECTED, MOVES, list(prof.values())), res)


# --- query.calendar -----------------------------------------------------

def calendar_db(week, playoff, with_settings=True):
    con = duckdb.connect()
    con.execute("create table v_leagues (league_key varchar, pull_id integer, "
                "season integer, current_week integer, is_finished boolean, "
                "start_date varchar, end_date varchar)")
    con.execute("insert into v_leagues values ('l', 1, 2025, ?, false, null, null)", [week])
    con.execute("create table v_league_settings (league_key varchar, pull_id integer, "
                "playoff_start_week integer, num_playoff_teams integer)")
    if with_settings:
        con.execute("insert into v_league_settings values ('l', 1, ?, 4)", [playoff])
    return con


from fantasy.query import calendar  # noqa: E402

before = calendar(calendar_db(10, 21))
check("mid-season is not in the playoffs", before["in_playoffs"], False)
check("and counts the weeks remaining", before["weeks_to_playoffs"], 11)

after = calendar(calendar_db(23, 21))
check("past the playoff week is in the playoffs", after["in_playoffs"], True)
check("with nothing left to count", after["weeks_to_playoffs"], 0)

no_settings = calendar(calendar_db(10, None, with_settings=False))
check("a missing settings row leaves the join null rather than failing",
      no_settings["playoff_start_week"], None)
check("and the playoff verdict stays false rather than guessing",
      no_settings["in_playoffs"], False)


# --- the whole document -------------------------------------------------

FIXTURE = {
    "schema_version": 1,
    "generated_at": "2026-09-04T10:00:00+00:00",
    "league": {"key": "l.1", "name": "Test League", "season": 2025, "teams": 3,
               "scoring_type": "head", "current_week": 23, "playoff_start_week": 21,
               "in_playoffs": True},
    "team": {"team_key": "me", "name": "KD's Burner Team", "manager": "Someone",
             "wins": 90, "losses": 87, "ties": 3, "standing": 1},
    "snapshot": {"pull_id": 1, "pulled_at": "2026-09-02T00:00:00", "age_days": 2.0},
    "model": {"sims": 4000, "seed": 0, "games_per_week": 3.5,
              "observed_period": "season", "stat_windows": ["season"],
              "horizon": "one_week"},
    "category_definitions": CATS,
    "caveats": [{"code": "season_complete", "severity": "blocking",
                 "message": "M.", "implication": "I."}],
    "roster": {"pool": 100, "projected": PROJECTED,
               "players": [{"player_key": "a", "name": "A|Pipe", "nba": "LAL",
                            "status": "Healthy", "pos": "PG", "gp": 70,
                            "pts": 20.0, "tov": 2.0, "fg": 0.45,
                            "pts_p": 0.9, "tov_p": 0.5, "fg_p": 0.1}]},
    "category_profile": list(prof.values()),
    "standings": STANDINGS,
    "opponents": [{"team_key": "b", "name": "B", "expected_cats_won": 3.5,
                   "p_win": 0.24}],
    "field": {"expected_cats_won": 4.35, "p_win": 0.48},
    "waivers": {
        "considered": {"free_agents": 16, "pairs": 96},
        "baseline": {"expected_cats_won": 4.35, "p_win": 0.48, "categories": {}},
        "moves": [], "best_by_player": [
            {"add": {"name": "Add One", "positions": ["C"], "nba": "ORL",
                     "status": "Healthy", "gp": 64.0, "player_key": "z"},
             "drop": {"name": "Drop One"}, "delta_cats": 0.33, "delta_p_win": 0.081,
             "categories": {"pts": 0.10, "tov": -0.04}, "add_profile": "strong REB"}],
        "drop_candidates": [{"name": "Drop One", "positions": ["C"], "slot": "C",
                             "cost": 0.30}]},
    "rules": {"facts": [{"label": "scoring", "value": "h2h", "source": "yahoo",
                         "note": "", "short": ""},
                        {"label": "lineups", "value": "daily", "source": "assumed",
                         "note": "why", "short": "daily"}]},
    "research": res,
}

doc = report.render_markdown(FIXTURE)
lines = doc.splitlines()

check("the document opens with front matter", lines[0], "---")
check("front matter carries the schema version", lines[1], "report_version: 1")
check("front matter closes before the body", lines.index("---", 1) > 1, True)
check("the version pinned in the file is the one rendered",
      f"report_version: {report.SCHEMA_VERSION}" in doc, True)

headings = [l for l in lines if l.startswith("## ")]
check("all seven sections render, in order",
      [h.split(".")[0] for h in headings],
      ["## 1", "## 2", "## 3", "## 4", "## 5", "## 6", "## 7"])
check("assumptions come before the research agenda, so the document ends on the ask",
      headings[5].startswith("## 6. Model assumptions")
      and headings[6].startswith("## 7. What to research"), True)

check("a team name with an apostrophe survives into the title",
      "# KD's Burner Team" in doc, True)
check("a pipe in a player name is escaped rather than splitting the row",
      "A\\|Pipe" in doc, True)
check("no Python None leaks into the document", "None" in doc, False)
check("the finished-season caveat is stated with its code",
      "`season_complete`" in doc, True)

# Every table must be rectangular, in every section.
def delimiters(line):
    """Pipes that actually split cells — an escaped \\| is content."""
    return len(re.findall(r"(?<!\\)\|", line))


ragged = []
for i, line in enumerate(lines):
    if not line.startswith("|"):
        continue
    width = delimiters(line)
    j = i
    while j < len(lines) and lines[j].startswith("|"):
        if delimiters(lines[j]) != width:
            ragged.append((j + 1, lines[j]))
        j += 1
check("every rendered table is rectangular", ragged, [])

# The optional win-rate column must vanish cleanly when there is nothing to show.
def section_three(text):
    return text.split("## 3.")[1].split("## 4.")[0]


no_p = dict(FIXTURE, category_profile=[dict(r, p_win=None) for r in prof.values()])
check("the win-rate column disappears when no probabilities were computed",
      "Win rate" in section_three(report.render_markdown(no_p)), False)
check("but is present when they were", "Win rate" in section_three(doc), True)
check("and section 4 keeps its own win-rate column either way",
      "Win rate" in report.render_markdown(no_p).split("## 4.")[1], True)

empty = dict(FIXTURE, waivers=dict(FIXTURE["waivers"], best_by_player=[], moves=[]))
check("an empty waiver pool says so rather than printing a bare header",
      "No legal improving move" in report.render_markdown(empty), True)

if failures:
    print(f"FAILED ({len(failures)}):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all report checks passed")
