"""
A standing report on the league, for a person or an agent to read.

This composes what the rest of the package already computes into one markdown
document. Its primary reader is an **agent** that will pair this report with
outside information — injury news, rotation changes, trades — and recommend
moves. So the report's job is not only to state what the model knows, but to be
explicit about what it does *not* know and to name where outside information
would change a conclusion. Section 7 exists entirely for that.

Two functions, and the split between them is the point:

    build(con, ...)        composes data, emits no prose, touches the database
    render_markdown(data)  emits the document, touches nothing else

That keeps a future HTML or JSON renderer an addition rather than a rewrite,
and it makes almost everything here testable without a database.

**Every analysis call must receive the same `sims`, `seed` and `games_per_week`.**
`matchup.prepare` reseeds a fresh generator over a deterministically ordered
player list, so identical arguments produce identical draws and the sections
agree with each other to within float32 accumulation. Vary them and section 3
will quietly contradict section 5.
"""
import dataclasses
from datetime import datetime, timezone
from pathlib import Path

from . import query
from .analysis import matchup, projection, waiver

# The section list, the section numbering and the data-quality vocabulary below
# are a contract: a downstream agent keys off them. Bump this when any of the
# three changes.
SCHEMA_VERSION = 1

# Where a report lands when no path is given. A single stable file, overwritten
# each run, so anything reading these reports — an agent especially — has one
# path to look at rather than having to work out which week is current. Pass an
# explicit --out to keep a dated copy alongside it.
DEFAULT_OUT = Path("reports/summary.md")

# Categories the model treats as mostly per-game randomness — 73-77% of their
# variance, per the decomposition in docs/ALGORITHMS.md. A strong rank in these
# is much less bankable than the same rank elsewhere, so the report flags them
# next to the number rather than only in the assumptions section.
NOISY = {"stl", "blk"}

# Percentile bounds for calling a player strong or weak in a category.
STRONG_P, WEAK_P = 0.80, 0.20


# --- small pure helpers -------------------------------------------------

def _esc(text) -> str:
    """Escape a value for a markdown table cell."""
    return "" if text is None else str(text).replace("|", "\\|")


def _cell(value, rate: bool = False, places: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}".lstrip("0") if rate else f"{value:,.{places}f}"
    return str(value)


def _record(entity: dict) -> str:
    """A win-loss-tie record, or an em dash when the snapshot has no standings."""
    parts = [entity.get("wins"), entity.get("losses"), entity.get("ties")]
    return "—" if all(p is None for p in parts) else "-".join(
        "0" if p is None else str(p) for p in parts)


def _pct(value, places: int = 1) -> str:
    return "—" if value is None else f"{100 * value:.{places}f}%"


def _signed(value, places: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:+.{places}f}{suffix}"


def _table(headers: list[str], rows: list[list], align: str | None = None) -> list[str]:
    """
    A markdown table. Rows must match the header width — a ragged row is a bug
    in the caller, not something to paper over with padding.
    """
    for i, row in enumerate(rows):
        if len(row) != len(headers):
            raise ValueError(
                f"row {i} has {len(row)} cells, expected {len(headers)}: {row!r}")
    align = align or "l" * len(headers)
    bar = {"l": "---", "r": "---:", "c": ":---:"}
    out = ["| " + " | ".join(_esc(h) for h in headers) + " |",
           "|" + "|".join(bar[a] for a in align) + "|"]
    out += ["| " + " | ".join(_esc(c) for c in row) + " |" for row in rows]
    return out


def _yaml_str(text) -> str:
    """
    Quote a scalar for YAML.

    Team names in this league include apostrophes ("KD's Burner Team"), and a
    name containing ": " would break a bare scalar outright.
    """
    if text is None:
        return "null"
    if isinstance(text, bool):
        return "true" if text else "false"
    if isinstance(text, (int, float)):
        return str(text)
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _yaml_block(mapping: dict, indent: int = 0) -> list[str]:
    pad = "  " * indent
    out = []
    for key, value in mapping.items():
        if isinstance(value, dict):
            out.append(f"{pad}{key}:")
            out += _yaml_block(value, indent + 1)
        elif isinstance(value, (list, tuple)):
            if not value:
                out.append(f"{pad}{key}: []")
            else:
                out.append(f"{pad}{key}:")
                out += [f"{pad}  - {_yaml_str(v)}" for v in value]
        else:
            out.append(f"{pad}{key}: {_yaml_str(value)}")
    return out


def _profile(player: dict, cats: list[dict]) -> str:
    """Name the categories where a player is unusually strong or weak."""
    strong = [c["label"] for c in cats if (player.get(c["key"] + "_p") or 0) >= STRONG_P]
    weak = [c["label"] for c in cats if (player.get(c["key"] + "_p") or 1) <= WEAK_P]
    parts = []
    if strong:
        parts.append("strong " + ", ".join(strong[:3]))
    if weak:
        parts.append("weak " + ", ".join(weak[:3]))
    return "; ".join(parts)


# --- data quality -------------------------------------------------------

def _data_quality(meta: dict, cal: dict, pull_age_days: float,
                  n_periods: int, identical_windows: bool,
                  fa_total: int, fa_usable: int, settings: dict,
                  schedule_used: bool = False) -> list[dict]:
    """
    What is wrong with this snapshot, as machine-readable codes plus prose.

    Freshness is deliberately not computed from pull age alone. A snapshot two
    days old can describe a season that finished months ago, and reporting it
    as fresh would be exactly backwards — so season state is evaluated first
    and dominates the wording.
    """
    out = []

    if cal.get("in_playoffs"):
        out.append({
            "code": "season_complete", "severity": "blocking",
            "message": (f"The pull is {pull_age_days:.0f} days old, but the season it "
                        f"describes is at or past its end: week {cal['current_week']} "
                        f"of a season whose playoffs began week {cal['playoff_start_week']}."),
            "implication": "Treat every projection as a description of finished "
                           "rosters, not of a live week.",
        })

    if identical_windows:
        out.append({
            "code": "identical_stat_windows", "severity": "material",
            "message": f"All {n_periods} stat windows (season, last_30, last_14, "
                       "last_7) hold identical figures.",
            "implication": "The recency blend contributed nothing. Any "
                           "'he's been hot lately' read is unsupported here.",
        })

    if fa_total <= 25:
        out.append({
            "code": "fa_pool_truncated", "severity": "blocking",
            "message": f"Only {fa_total} free agents were pulled into the snapshot "
                       f"({fa_usable} of them clear the model's games filter), which "
                       "means --fa-limit was used.",
            "implication": "Section 5 searched a fraction of the real pool. The "
                           "best available add is very likely not listed. Re-run "
                           "`fantasy pull` without --fa-limit before acting.",
        })

    out.append({
        "code": "no_scoreboard", "severity": "material",
        "message": "The store has no matchup or scoreboard table.",
        "implication": "Nothing here knows who you play this week, or how past "
                       "weeks actually finished. Section 4 measures you against "
                       "all opponents instead.",
    })
    if schedule_used:
        out.append({
            "code": "schedule_not_week_specific", "severity": "note",
            "message": "Games/week now comes from each NBA team's real schedule "
                       f"({cal.get('games_per_week', 0):.2f}/week league average), but "
                       "the snapshot has no fantasy-week calendar, so it is fit to a "
                       "typical week of the season rather than matched to the actual "
                       "dates of the current matchup.",
            "implication": "Treat game counts as realistic, not as a confirmed count "
                           "for this specific week — a bye week or a Cup-heavy week "
                           "would be missed.",
        })
    else:
        out.append({
            "code": "no_schedule", "severity": "material",
            "message": "No NBA schedule pulled, so every team is assumed to play "
                       f"{cal.get('games_per_week', 3.5)} games a week.",
            "implication": "44-49% of the variance in the volume categories is how "
                           "many games actually get played (docs/ALGORITHMS.md). Run "
                           "`fantasy schedule pull`.",
        })
    out.append({
        "code": "not_backtested", "severity": "material",
        "message": "No probability in this report has ever been compared "
                   "against a real weekly result.",
        "implication": "Say 'the model puts this at 34%', not 'you have a 34% "
                       "chance'.",
    })

    if any(v is None for k, v in settings.items()
           if k in ("num_playoff_teams", "waiver_type", "uses_faab")):
        out.append({
            "code": "settings_incomplete", "severity": "note",
            "message": "League settings are mostly NULL apart from "
                       "playoff_start_week.",
            "implication": "Playoff team count, waiver type and FAAB are unknown, "
                           "so an add is assumed free.",
        })

    out.append({
        "code": "scoring_mode_inferred", "severity": "note",
        "message": "Every team's record sums to the same total, which implies "
                   "each category is scored as its own win/loss. Yahoo's "
                   "scoring_type only says 'head'.",
        "implication": "Expected categories won is the metric that matches this "
                       "league; 'chance to win the matchup' is a derived "
                       "convenience.",
    })
    return out


# --- section data -------------------------------------------------------

def _category_profile(standings: dict, my_key: str, field_cats: dict,
                      cat_defs: list[dict]) -> list[dict]:
    """
    My output per category against the league, with rank and the gap that would
    move it.

    `field_cats` maps a category key to an average win probability and may be
    empty, in which case the probability column is simply absent downstream.
    """
    teams = standings["teams"]
    rows = []
    for cat in cat_defs:
        key, neg = cat["key"], bool(cat.get("neg"))
        vals = [(t["team_key"], t["totals"].get(key)) for t in teams
                if t["totals"].get(key) is not None]
        vals.sort(key=lambda x: x[1], reverse=not neg)
        order = [tk for tk, _ in vals]
        by_key = dict(vals)

        mine = by_key.get(my_key)
        rank = order.index(my_key) + 1 if my_key in order else None
        # The value one rank better — how far off flipping a place actually is.
        gap = None
        if rank and rank > 1:
            gap = abs(mine - by_key[order[rank - 2]])

        numbers = [v for _, v in vals]
        median = sorted(numbers)[len(numbers) // 2] if numbers else None
        rows.append({
            "key": key, "label": cat["label"], "neg": neg,
            "rate": bool(cat.get("rate")), "noisy": key in NOISY,
            "mine": mine, "median": median,
            "best": numbers[0] if numbers else None,
            "rank": rank, "teams": len(vals), "gap_to_next": gap,
            "p_win": field_cats.get(key),
        })
    rows.sort(key=lambda r: (r["p_win"] is None, -(r["p_win"] or 0)))
    return rows


def _research_targets(roster_players: list[dict], projected: dict,
                      best_moves: list[dict], profile: list[dict]) -> dict:
    """
    Where outside information would change a conclusion, most valuable first.

    Roster players are ranked by the effective sample behind their rates: a low
    number means the model is guessing, which is exactly where a news item moves
    the answer most. Injury status and an IL slot are treated the same way —
    both mean the projection rests on something the snapshot cannot see.
    """
    unsure = []
    for p in roster_players:
        proj = projected.get(p["player_key"])
        if not proj:
            continue
        on_il = p.get("pos") == "IL"
        unhealthy = (p.get("status") or "Healthy") != "Healthy"
        if not (on_il or unhealthy or proj.n_eff < 40):
            continue
        reasons = [f"{int(proj.n_eff)}-game sample"]
        if unhealthy:
            reasons.append(str(p["status"]))
        if on_il:
            reasons.append("on IL, contributes nothing")
        unsure.append({
            "name": p["name"], "nba": p.get("nba"), "slot": p.get("pos"),
            "why": ", ".join(reasons),
            "n_eff": proj.n_eff, "p_play": proj.p_play,
            "sort": (0 if on_il else 1, proj.n_eff),
        })
    unsure.sort(key=lambda r: r["sort"])

    improving = [m for m in best_moves if m["delta_cats"] > 0]

    # Deficits a single move could flip: ranked worse than mid-table, ordered by
    # how little separates them from the next rank up.
    flippable = [r for r in profile
                 if r["rank"] and r["teams"] and r["rank"] > r["teams"] / 2
                 and r["gap_to_next"] is not None]
    flippable.sort(key=lambda r: r["rank"] and -r["rank"])

    return {"uncertain_players": unsure[:6], "adds_to_verify": improving[:5],
            "flippable_categories": flippable[:4],
            "ignore_categories": [r["label"] for r in profile if r["noisy"]]}


# --- build --------------------------------------------------------------

def build(con, team: str | None = None, sims: int = 10000, seed: int = 0,
          games_per_week: float | None = None,
          periods: list[str] | None = None, top: int = 10, drops: int = 6,
          min_gp: float = 5.0, now: datetime | None = None) -> dict:
    """
    Everything the report needs, as plain data. No formatting happens here.

    `now` is injectable so a test can pin the generated timestamp.
    """
    now = now or datetime.now(timezone.utc)
    meta = query.meta(con)
    cal = query.calendar(con)
    me = matchup.resolve_team(con, team)
    my_key = me["team_key"]

    my_row = next((t for t in meta["teams"] if t["team_key"] == my_key), {})
    roster = query.roster(con, my_key, "season")
    standings = query.standings(con, "season")
    fa = query.free_agents(con, "season")

    # Both analysis calls take identical arguments — see the module docstring.
    field = matchup.versus_field(con, team, periods, sims, seed, games_per_week)
    moves = waiver.add_drop(con, team, None, periods, sims, seed, games_per_week,
                            drops, top, min_gp)

    rules = dataclasses.asdict(field["rules"])   # never let the dataclass escape
    cat_defs = rules["categories"]
    field_cats = {c["key"]: c["p_win"] for c in field["categories"]}
    gpw = field["games_per_week"]                # the resolved rate, real or overridden
    schedule_used = any(f["label"] == "games per team" and f["source"] == "nba.com"
                        for f in rules["facts"])

    projected = {p.player_key: p for p in projection.build(con, periods, games_per_week)}
    fa_by_key = {p["player_key"]: p for p in fa["players"]}

    pull_at = datetime.fromisoformat(meta["pull"]["at"])
    if pull_at.tzinfo is None:
        pull_at = pull_at.replace(tzinfo=timezone.utc)
    age_days = (now - pull_at).total_seconds() / 86400

    # The real pool size, not query.free_agents' count — that drops anyone with
    # no games played, which understates how truncated the pull was.
    fa_pool_size = con.execute(
        "select count(*) from v_rosters where is_free_agent").fetchone()[0]

    settings = con.execute(
        "select num_playoff_teams, waiver_type, uses_faab from v_league_settings"
    ).fetchone() or (None, None, None)
    settings = dict(zip(["num_playoff_teams", "waiver_type", "uses_faab"], settings))

    # Windows are "identical" when no player's points differ across them, which
    # is what an off-season pull produces and what makes the recency blend inert.
    n_periods = len(meta["periods"])
    identical = n_periods > 1 and con.execute("""
        select count(*) = 0 from (
            select player_key from v_player_stats where stat_name = 'PTS'
            group by player_key having count(distinct value) > 1)
    """).fetchone()[0]

    profile = _category_profile(standings, my_key, field_cats, cat_defs)

    for move in moves["moves"] + moves["best_by_player"]:
        move["add_profile"] = _profile(fa_by_key.get(move["add"]["player_key"], {}),
                                       cat_defs)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.replace(microsecond=0).isoformat(),
        "league": {**meta["league"], "key": meta["pull"]["league_key"], **cal},
        "team": {**me, **{k: my_row.get(k) for k in
                          ("wins", "losses", "ties", "standing")}},
        "snapshot": {"pull_id": meta["pull"]["id"], "pulled_at": meta["pull"]["at"],
                     "age_days": round(age_days, 1)},
        "model": {"sims": sims, "seed": seed, "games_per_week": gpw,
                  "observed_period": "season", "stat_windows": meta["periods"],
                  "horizon": "one_week"},
        "category_definitions": cat_defs,
        "caveats": _data_quality(meta, {**cal, "games_per_week": gpw},
                                 age_days, n_periods, identical, fa_pool_size,
                                 moves["considered"]["free_agents"], settings,
                                 schedule_used),
        "roster": {"players": roster["players"], "pool": roster["pool"],
                   "projected": projected},
        "category_profile": profile,
        "standings": standings,
        "opponents": field["opponents"],
        "field": {"expected_cats_won": field["expected_cats_won"],
                  "p_win": field["p_win"]},
        "waivers": moves,
        "rules": rules,
        "research": _research_targets(roster["players"], projected,
                                      moves["best_by_player"], profile),
    }


# --- render -------------------------------------------------------------

def _front_matter(d: dict) -> list[str]:
    league, team = d["league"], d["team"]
    return ["---"] + _yaml_block({
        "report_version": d["schema_version"],
        "league": {
            "key": league.get("key"), "name": league.get("name"),
            "season": league.get("season"), "teams": league.get("teams"),
            "scoring_type": league.get("scoring_type"),
            "scoring_mode": "per_category (inferred)",
            "current_week": league.get("current_week"),
            "playoff_start_week": league.get("playoff_start_week"),
            "in_playoffs": league.get("in_playoffs"),
        },
        "team": {
            "key": team.get("team_key"), "name": team.get("name"),
            "manager": team.get("manager"), "standing": team.get("standing"),
            "record": _record(team),
        },
        "snapshot": d["snapshot"],
        "model": d["model"],
        "data_quality": [c["code"] for c in d["caveats"]],
        "generated_at": d["generated_at"],
    }) + ["---", ""]


def _s1_snapshot(d: dict) -> list[str]:
    league, team, snap = d["league"], d["team"], d["snapshot"]
    record = _record(team)
    out = [
        "## 1. Snapshot and caveats", "",
        "This report contains **no news**. Everything below comes from one DuckDB",
        "snapshot of the league. Nothing here knows about an injury, trade or",
        "rotation change that happened after the pull.", "",
    ]
    out += _table(["", ""], [
        ["League", f"{league.get('name')} ({league.get('season')}, "
                   f"{league.get('teams')} teams)"],
        ["My team", f"{team.get('name')} ({team.get('manager')})"],
        ["Category record", f"{record} — each week awards one win or loss per category"],
        ["Standing", f"{team.get('standing')} — does not follow the record, so it "
                     "most likely reflects a playoff finish"],
        ["Snapshot", f"pull #{snap['pull_id']}, {snap['pulled_at'][:10]} "
                     f"({snap['age_days']:.0f} days ago)"],
        ["League week", f"{league.get('current_week')}, playoffs began week "
                        f"{league.get('playoff_start_week')}"],
        ["Model", f"{d['model']['sims']:,} simulated weeks, seed "
                  f"{d['model']['seed']}, {d['model']['games_per_week']:.2f} games/team"],
    ])
    out += ["", "**Read these before acting on any number below.**", ""]
    for c in d["caveats"]:
        out.append(f"- **`{c['code']}`** — {c['message']} {c['implication']}")
    return out + [""]


def _s2_roster(d: dict) -> list[str]:
    cats = d["category_definitions"]
    projected = d["roster"]["projected"]
    headers = (["Slot", "Player", "NBA", "Status", "GP", "n_eff", "Avail"]
               + [c["label"] for c in cats] + ["Profile"])
    align = "lllrrrr" + "r" * len(cats) + "l"

    rows = []
    for p in d["roster"]["players"]:
        proj = projected.get(p["player_key"])
        rows.append(
            [p.get("pos") or "—", p["name"], p.get("nba") or "—",
             p.get("status") or "—", p.get("gp"),
             f"{proj.n_eff:.0f}" if proj else "—",
             f"{proj.p_play:.2f}" if proj else "—"]
            + [_cell(p.get(c["key"]), rate=c.get("rate")) for c in cats]
            + [_profile(p, cats)])

    unhealthy = sum(1 for p in d["roster"]["players"]
                    if (p.get("status") or "Healthy") != "Healthy")
    il = sum(1 for p in d["roster"]["players"] if p.get("pos") == "IL")
    return [
        "## 2. My roster", "",
        "Per-game averages over the season window. `n_eff` is the effective sample",
        "behind those rates — a low number means the projection is a guess. `Avail`",
        "is the model's chance the player appears in a given scheduled game, from",
        "injury status and games missed. IL players are listed but contribute",
        f"nothing to any simulation below. Percentiles rank against all "
        f"{d['roster']['pool']} rostered players in the league.", "",
    ] + _table(headers, rows, align) + [
        "",
        f"{unhealthy} of {len(rows)} carry a non-Healthy status and {il} sit on IL. "
        "Those statuses come from the snapshot and are the single largest lever on "
        "every number in this report — section 7 lists which to check first.", "",
    ]


def _s3_profile(d: dict) -> list[str]:
    rows_in = d["category_profile"]
    has_p = any(r["p_win"] is not None for r in rows_in)
    headers = ["Cat", "Mine", "Median", "Best", "Rank", "Gap to next"]
    align = "lrrrrr"
    if has_p:
        headers.append("Win rate")
        align += "r"
    headers.append("Note")
    align += "l"

    rows = []
    for r in rows_in:
        note = []
        if r["noisy"]:
            note.append("~75% per-game noise")
        if r["neg"]:
            note.append("lower is better")
        row = [r["label"], _cell(r["mine"], r["rate"]), _cell(r["median"], r["rate"]),
               _cell(r["best"], r["rate"]),
               f"{r['rank']} / {r['teams']}" if r["rank"] else "—",
               _cell(r["gap_to_next"], r["rate"])]
        if has_p:
            row.append(_pct(r["p_win"]))
        row.append("; ".join(note))
        rows.append(row)

    out = [
        "## 3. Category profile against the league", "",
        "**`Mine` is the sum of per-game averages across my non-IL rostered players.**",
        "It is not a weekly total and carries no injury discount, so it does not",
        "match the simulated weekly figures the model uses elsewhere — the two are",
        "different quantities and should not be reconciled. Ranks use the same",
        "measure for all teams.", "",
    ]
    if has_p:
        out += [
            "`Win rate` is a different thing again: the share of simulated weeks in",
            "which this roster beats a randomly chosen opponent in that category. It",
            "does price in availability and week-to-week variance, so where rank and",
            "win rate disagree, the win rate is the one that reflects a real week.", "",
        ]
    out += _table(headers, rows, align)
    out += ["", f"Mean rank {d['standings'] and _mean_rank(d)} of "
                f"{rows_in[0]['teams'] if rows_in else '—'}. Expected "
                f"{d['field']['expected_cats_won']:.2f} of {len(rows_in)} categories "
                f"against an average opponent.", ""]

    overlap = sorted({r["label"] for r in rows_in[:2]} &
                     {r["label"] for r in rows_in if r["noisy"]})
    if overlap:
        subject = (f"{overlap[0]} is" if len(overlap) == 1
                   else f"{' and '.join(overlap)} are")
        out += [f"Worth noting that {subject} among my strongest categories and also "
                "one the model treats as mostly noise — a good rank there is not "
                "something to build a plan on." if len(overlap) == 1 else
                f"Worth noting that {subject} among my strongest categories and also "
                "ones the model treats as mostly noise — a good rank there is not "
                "something to build a plan on.", ""]
    return out


def _mean_rank(d: dict):
    me = next((t for t in d["standings"]["teams"] if t["is_my_team"]), None)
    return me.get("mean_rank") if me else "—"


def _s4_landscape(d: dict) -> list[str]:
    cats = d["category_definitions"]
    rows = []
    for t in d["standings"]["teams"]:
        name = t["name"] + (" *(me)*" if t["is_my_team"] else "")
        rows.append([name, t.get("manager") or "—", _record(t),
                     t.get("standing") or "—"]
                    + [t["ranks"].get(c["key"]) or "—" for c in cats]
                    + [t.get("mean_rank")])

    opp_rows = [[o["name"], f"{o['expected_cats_won']:.2f}", _pct(o["p_win"])]
                for o in d["opponents"]]
    return [
        "## 4. League landscape", "",
        "### Standings and category ranks", "",
        "Same measure as section 3, for every team. Records are per-category — each",
        "week awards one win or loss in each — which is why the standing order does",
        "not follow the win column.", "",
    ] + _table(["Team", "Manager", "Record", "Std"] + [c["label"] for c in cats] + ["Mean"],
               rows, "lllr" + "r" * len(cats) + "r") + [
        "", "### Who is hard for me", "",
        "Simulated weeks against each opponent's current roster, toughest first.",
        "There is no scoreboard data in the snapshot, so this is every opponent",
        "rather than this week's.", "",
    ] + _table(["Opponent", "Expected cats won", "Win rate"], opp_rows, "lrr") + [
        "", f"Against an average opponent: {d['field']['expected_cats_won']:.2f} of "
            f"{len(cats)} categories, {_pct(d['field']['p_win'])} to take the week.", "",
    ]


def _s5_waivers(d: dict) -> list[str]:
    w = d["waivers"]
    cat_label = {c["key"]: c["label"] for c in d["category_definitions"]}
    # One row per free agent, each paired with the drop that suits them best.
    # The raw `moves` list is ranked by delta alone, so a single strong add
    # occupies most of it paired with six different drops — the same decision
    # six times over rather than six options.
    moves = w["best_by_player"]
    improving = [m for m in moves if m["delta_cats"] > 0]

    out = [
        "## 5. Waiver opportunities", "",
        f"{w['considered']['free_agents']} free agents cleared the games filter and "
        f"{w['considered']['pairs']} legal add/drop pairs were evaluated against the "
        f"whole league. **{len(improving)} of the {len(moves)} free agents below "
        "improve the week.** Each is shown with the drop that suits it best. "
        "Every candidate is scored against the same simulated weeks as the baseline, "
        "so the ordering carries no sampling noise of its own — trust it further than "
        "the magnitudes.", "",
        f"Baseline: {w['baseline']['expected_cats_won']:.2f} expected categories, "
        f"{_pct(w['baseline']['p_win'])} to win a week.", "",
    ]

    if not moves:
        out += ["No legal improving move was found in the pool available.", ""]
        return out

    rows = []
    for m in moves:
        gains = sorted(m["categories"].items(), key=lambda kv: -kv[1])
        up = ", ".join(f"{cat_label.get(k, k)} {100 * v:+.0f}"
                       for k, v in gains[:3] if v > 0.01) or "—"
        down = ", ".join(f"{cat_label.get(k, k)} {100 * v:+.0f}"
                         for k, v in gains[-2:] if v < -0.01) or "—"
        rows.append([m["add"]["name"], "/".join(m["add"]["positions"][:3]),
                     m["add"]["nba"] or "—", m["add"]["status"] or "—",
                     m["add"]["gp"], m["drop"]["name"],
                     _signed(m["delta_cats"]), _signed(100 * m["delta_p_win"], 1, "pp"),
                     up, down, m.get("add_profile", "")])
    out += _table(["Add", "Pos", "NBA", "Status", "GP", "Drop", "Cats", "Win",
                   "Gains (pp)", "Costs (pp)", "Add's profile"],
                  rows, "lllrrlrrlll")

    dropped = {m["drop"]["name"] for m in improving}
    if improving and len(dropped) == 1:
        out += ["", f"Every improving move drops the same player, {dropped.pop()} — "
                    "so this is one decision about that roster spot, not several "
                    "independent moves.", ""]
    else:
        out += [""]

    out += [
        "### Cheapest to drop", "",
        "`Cost` is expected categories lost by playing without the player. It prices",
        "against a **short roster**, not against a replacement, so it overvalues",
        "everyone — a shortlist, not a valuation.", "",
    ] + _table(["Player", "Pos", "Slot", "Cost (cats)"],
               [[c["name"], "/".join(c["positions"][:3]), c.get("slot") or "—",
                 f"{c['cost']:.2f}"] for c in w["drop_candidates"]], "lllr") + [
        "", "*Deltas are stable to about ±0.01 categories between seeds; absolute "
            "probabilities move about a point. Adds are assumed obtainable at no "
            "cost — waiver priority and FAAB are not in the snapshot.*", "",
    ]
    return out


def _s6_assumptions(d: dict) -> list[str]:
    facts = d["rules"]["facts"]
    read = [[f["label"], f["value"], f["source"]] for f in facts if f["source"] != "assumed"]
    assumed = [[f["label"], f["value"], f["note"]] for f in facts
               if f["source"] == "assumed"]
    out = ["## 6. Model assumptions", "", "Not assumed — read from real data:", ""]
    out += _table(["Rule", "Value", "Source"], read)
    out += ["", "Assumed, because the snapshot does not carry them:", ""]
    out += _table(["Rule", "Value", "Why it matters"], assumed)
    return out + [
        "", "Model-level limits:", "",
        "- **Nothing here is backtested.** No comparison against real weekly results",
        "  exists in this project. Say \"the model puts this at 34%\", not \"you have",
        "  a 34% chance\".",
        "- Steals and blocks are 73-77% per-game noise. A small edge there is not a",
        "  finding.",
        "- Players are drawn independently, which understates the variance of a",
        "  roster stacked on few NBA teams.",
        "- **Every objective here scores exactly one week.** There is no multi-week",
        "  or playoff-horizon model. Anything longer than a week is your judgement,",
        "  not this report's.", "",
    ]


def _s7_research(d: dict) -> list[str]:
    r = d["research"]
    out = [
        "## 7. What to research before recommending anything", "",
        f"This report knows nothing after {d['snapshot']['pulled_at'][:10]}. These are",
        "the specific places where outside information would change a conclusion",
        "above, most valuable first.", "",
    ]

    if r["uncertain_players"]:
        out += ["### Roster players the model is least sure about", ""]
        out += _table(
            ["Player", "NBA", "Slot", "Why the model is unsure", "Avail"],
            [[p["name"], p["nba"] or "—", p["slot"] or "—", p["why"],
              f"{p['p_play']:.2f}"] for p in r["uncertain_players"]], "llllr")
        out += [""]

    if r["adds_to_verify"]:
        out += ["### Free agents worth verifying", "",
                "Is the player still available, and has the role that produced these",
                "rates changed since the pull?", ""]
        out += _table(["Player", "Model's claim"],
                      [[m["add"]["name"],
                        f"{_signed(m['delta_cats'])} expected categories, dropping "
                        f"{m['drop']['name']}"] for m in r["adds_to_verify"]])
        out += [""]

    if r["flippable_categories"]:
        out += ["### Categories where one move could flip a rank", ""]
        for c in r["flippable_categories"]:
            out.append(f"- **{c['label']}** — {c['rank']} of {c['teams']}, "
                       f"{_cell(c['gap_to_next'], c['rate'])} behind the next rank up.")
        out += [""]

    if r["ignore_categories"]:
        out += [f"Weigh news in **{' and '.join(r['ignore_categories'])}** lightly "
                "whatever the rank — the model treats roughly three quarters of "
                "their per-game movement as noise.", ""]

    out += [
        "### Folding what you find back in", "",
        "This report has no news and no NBA schedule. Once you have both: correct",
        "availability by hand for anyone whose status you have verified, then re-run",
        f"`fantasy waivers --sims {d['model']['sims']} --seed {d['model']['seed']}` so",
        "the numbers stay comparable with the ones above. Changing the seed moves",
        "absolute probabilities by about a point.", "",
    ]
    return out


SECTIONS = [_s1_snapshot, _s2_roster, _s3_profile, _s4_landscape,
            _s5_waivers, _s6_assumptions, _s7_research]


def render_markdown(data: dict) -> str:
    """The whole document. Touches no database and runs no simulation."""
    team = data["team"].get("name", "Report")
    week = data["league"].get("current_week")
    lines = _front_matter(data)
    lines += [f"# {team}" + (f" — week {week}" if week else ""), ""]
    for section in SECTIONS:
        lines += section(data)
    return "\n".join(lines).rstrip() + "\n"
