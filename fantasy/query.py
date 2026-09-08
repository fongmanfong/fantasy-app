"""
Read-side queries over the latest DuckDB snapshot.

Every function takes an open connection and returns plain dicts, so the HTTP
layer is a thin shell around this module and the same calls work from a REPL.
"""
from .names import normalize

COUNTING = ["pts", "reb", "ast", "stl", "blk", "tpm", "tov"]
RATES = ["fg", "ft"]
# Categories as the league scores them, in display order. `neg` marks the one
# where a low number wins, which flips both shading and head-to-head edges.
CATEGORIES = [
    {"key": "pts", "label": "PTS"},
    {"key": "reb", "label": "REB"},
    {"key": "ast", "label": "AST"},
    {"key": "stl", "label": "ST"},
    {"key": "blk", "label": "BLK"},
    {"key": "tpm", "label": "3PM"},
    {"key": "tov", "label": "TO", "neg": True},
    {"key": "fg", "label": "FG%", "rate": True},
    {"key": "ft", "label": "FT%", "rate": True},
]
# The categories where a low number wins. Derived from CATEGORIES rather than
# named literally, so a league whose inverted category is not turnovers picks it
# up from `rules.load` without a second list to keep in sync.
NEGATIVE = {c["key"] for c in CATEGORIES if c.get("neg")}


def beats(a, b, cat: dict):
    """
    Whether `a` wins this category against `b`.

    The one place the inverted category flips a comparison. Works on scalars
    and on numpy arrays alike, which is why the simulator's element-wise
    win masks and this module's team-vs-team edges can share it.
    """
    return (a < b) if cat.get("neg") else (a > b)


def player_keys_by_name(con) -> dict[str, str]:
    """
    normalized full_name -> player_key, from the latest league snapshot.

    The join every outside source goes through — a ranking site, nba.com — so
    that all of them resolve a name the same way. Returns an empty map rather
    than raising when there is no snapshot yet: an outside pull is still worth
    storing unmatched, and dropping its rows would hide the miss.
    """
    try:
        rows = con.execute("SELECT full_name, player_key FROM v_players").fetchall()
    except Exception:
        return {}
    out: dict[str, str] = {}
    for full_name, player_key in rows:
        if full_name and player_key:
            out.setdefault(normalize(full_name), player_key)
    return out


def latest_pull(con) -> dict:
    """
    The newest successful pull: `id`, `league_key`, and `at` as an ISO string.

    Every `v_*` view already resolves to this pull, so this is for stamping and
    reporting rather than for filtering — a query that joins a view does not
    need to mention the pull id.
    """
    row = con.execute(
        "select p.pull_id, p.league_key, p.pulled_at from latest_pull lp "
        "join pulls p using (pull_id, league_key) limit 1"
    ).fetchone()
    if not row:
        raise RuntimeError("No successful pull in the database yet. Run `fantasy pull`.")
    return {"id": row[0], "league_key": row[1], "at": row[2].isoformat()}


def calendar(con) -> dict:
    """
    Where the season is: the current week, the playoff boundary, and whether
    it has finished.

    `meta` deliberately does not carry these — it backs the `/api/meta` payload
    and widening it would change that contract. Settings arrive from a LEFT
    JOIN because `league_settings` is mostly NULL on older snapshots.
    """
    row = con.execute("""
        select l.season, l.current_week, l.is_finished, l.start_date, l.end_date,
               s.playoff_start_week, s.num_playoff_teams
        from v_leagues l
        left join v_league_settings s using (league_key, pull_id)
        limit 1
    """).fetchone()
    if not row:
        raise RuntimeError("No league in the snapshot. Run `fantasy pull` first.")

    keys = ["season", "current_week", "is_finished", "start_date", "end_date",
            "playoff_start_week", "num_playoff_teams"]
    out = dict(zip(keys, row))

    week, playoff = out["current_week"], out["playoff_start_week"]
    out["in_playoffs"] = bool(week and playoff and week >= playoff)
    out["weeks_to_playoffs"] = (playoff - week) if (week and playoff and week < playoff) else 0
    return out


def _names(con, pull_id: int) -> dict:
    """
    Stat names for this pull.

    Rows written before the stat-map fix carry makes and attempts reversed.
    They are identifiable because the legacy replay left `stat_id` null, while
    a real pull always sets it.
    """
    legacy = con.execute(
        "select count(*) = 0 from player_stats where pull_id = ? and stat_id is not null",
        [pull_id],
    ).fetchone()[0]
    if legacy:
        return {"tpm": "3PTA", "fgm": "FGA", "fga": "FGM",
                "ftm": "FTA", "fta": "FTM", "legacy": True}
    return {"tpm": "3PTM", "fgm": "FGM", "fga": "FGA",
            "ftm": "FTM", "fta": "FTA", "legacy": False}


def _players(con, period: str) -> list[dict]:
    """
    Every rostered player and free agent for one period, as per-game rates.

    The counting stats are divided by games played here; FG% and FT% arrive
    from Yahoo already as percentages and are passed through untouched, as are
    the makes and attempts behind them. Players with no games in the period are
    dropped, and an unknown period raises with the list of ones the snapshot has.
    """
    pull = latest_pull(con)
    n = _names(con, pull["id"])

    def pick(stat, alias):
        return f"max(case when st.stat_name = '{stat}' then st.value end) as {alias}"

    cols = ", ".join([
        pick("GP", "gp"), pick("PTS", "pts"), pick("REB", "reb"), pick("AST", "ast"),
        pick("ST", "stl"), pick("BLK", "blk"), pick(n["tpm"], "tpm"), pick("TO", "tov"),
        pick("FG%", "fg"), pick("FT%", "ft"),
        pick(n["fgm"], "fgm"), pick(n["fga"], "fga"),
        pick(n["ftm"], "ftm"), pick(n["fta"], "fta"),
    ])

    rows = con.execute(f"""
        select r.team_key, r.player_key, p.full_name, p.editorial_team_abbr,
               p.status, p.positions, r.selected_position, r.is_free_agent, {cols}
        from v_rosters r
        join v_players p using (league_key, player_key)
        join v_player_stats st using (league_key, player_key)
        where st.stat_period = ?
        group by 1,2,3,4,5,6,7,8
    """, [period]).fetchall()
    keys = [d[0] for d in con.description]
    recs = [dict(zip(keys, r)) for r in rows]
    recs = [r for r in recs if (r["gp"] or 0) > 0]

    if not recs:
        have = [r[0] for r in con.execute(
            "select distinct stat_period from v_player_stats order by 1").fetchall()]
        raise RuntimeError(
            f"No stats for period {period!r}. Available: {', '.join(have) or 'none'}")

    for r in recs:
        for k in COUNTING:
            r[k] = (r[k] or 0) / r["gp"]
    return recs


def _percentiles(pool: list[dict]) -> dict:
    """Sorted value lists per category, for ranking any player against the pool."""
    return {k: sorted(x[k] for x in pool if x[k] is not None)
            for k in COUNTING + RATES}


def _percentile_of(sorted_vals: list, value, neg: bool) -> float:
    """
    Where `value` falls in a sorted pool, 0-1, with 1 always the good end.

    A missing value or an empty pool scores 0.5 rather than 0: an unknown is
    not evidence of weakness, and zero would drag a player down a category they
    simply have no reading in.
    """
    if not sorted_vals or value is None:
        return 0.5
    below = sum(1 for v in sorted_vals if v < value) / len(sorted_vals)
    return round(1 - below if neg else below, 3)


def _shape(rec: dict, dist: dict) -> dict:
    """
    One player as the interface wants them: rounded values plus, for every
    category, a `<key>_p` percentile against `dist` where 1 is always good.
    """
    p = {"player_key": rec["player_key"], "name": rec["full_name"],
         "nba": rec["editorial_team_abbr"], "status": rec["status"],
         "pos": rec["selected_position"], "gp": int(rec["gp"]),
         "positions": list(rec["positions"] or [])}
    for k in COUNTING + RATES:
        v = rec[k]
        p[k] = round(v, 3) if v is not None else None
        p[k + "_p"] = _percentile_of(dist[k], v, neg=(k in NEGATIVE))
    return p


def meta(con) -> dict:
    """
    Everything an interface needs before it asks for players: the league, its
    teams in standings order, the stat periods the snapshot holds, the display
    categories, the league's own scoring categories, the pull it all came from,
    and `legacy_names` — true when this snapshot predates the stat-map fix and
    has makes and attempts transposed.

    This backs `/api/meta` and is treated as a fixed contract; season and
    playoff dates live in `calendar` instead.
    """
    pull = latest_pull(con)
    league = con.execute(
        "select name, season, num_teams, scoring_type from v_leagues limit 1").fetchone()
    teams = [dict(zip(["team_key", "name", "manager", "is_my_team",
                       "wins", "losses", "ties", "standing"], r))
             for r in con.execute(
                 "select team_key, name, manager_name, is_my_team, wins, losses, "
                 "ties, standing from v_teams order by standing nulls last").fetchall()]
    periods = [r[0] for r in con.execute(
        "select distinct stat_period from v_player_stats order by 1").fetchall()]
    cats = [dict(zip(["stat_id", "name", "display_name", "is_only_display"], r))
            for r in con.execute(
                "select stat_id, name, display_name, is_only_display "
                "from v_stat_categories order by name").fetchall()]
    return {
        "league": {"name": league[0], "season": league[1],
                   "teams": league[2], "scoring_type": league[3]},
        "teams": teams, "periods": periods, "categories": CATEGORIES,
        "scoring_categories": cats, "pull": pull,
        "legacy_names": _names(con, pull["id"])["legacy"],
    }


def _ranked(con, period: str, keep) -> dict:
    """
    Shape and sort a subset of the pool, ranked against **rostered** players.

    Percentiles always come from the rostered population, never from whoever
    `keep` selects: a free agent's 60th percentile has to mean the same thing
    as a starter's, which it would not if the free-agent pool were ranked
    against itself.
    """
    recs = _players(con, period)
    rostered = [r for r in recs if not r["is_free_agent"]]
    dist = _percentiles(rostered)
    players = [_shape(r, dist) for r in recs if keep(r)]
    players.sort(key=lambda p: -(p["pts"] or 0))
    return {"players": players, "pool": len(rostered), "period": period}


def roster(con, team_key: str, period: str = "season") -> dict:
    """One team's players, best first, with percentiles against the league."""
    return _ranked(con, period,
                   lambda r: not r["is_free_agent"] and r["team_key"] == team_key)


def free_agents(con, period: str = "season") -> dict:
    """The unrostered pool, best first, ranked against rostered players."""
    return _ranked(con, period, lambda r: r["is_free_agent"])


def _team_totals(recs: list[dict], team_key: str) -> dict:
    """
    A team's weekly output: counting rates summed over active players, and
    percentages weighted by real makes and attempts rather than averaged.
    """
    active = [r for r in recs
              if r["team_key"] == team_key
              and not r["is_free_agent"]
              and r["selected_position"] != "IL"]
    out = {k: sum(r[k] or 0 for r in active) for k in COUNTING}
    for rate, made, att in (("fg", "fgm", "fga"), ("ft", "ftm", "fta")):
        m = sum(r[made] or 0 for r in active)
        a = sum(r[att] or 0 for r in active)
        out[rate] = round(m / a, 4) if a else None
    out = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out.items()}
    out["players"] = len(active)
    return out


def standings(con, period: str = "season") -> dict:
    """
    Every team's category totals, their rank in each (1 is best, and low
    turnovers rank first), and their `mean_rank` across categories.

    These are summed per-game averages over each team's non-IL players — a
    measure of roster shape, not a projection of a week. `matchup.versus_field`
    is what answers "would they win".
    """
    recs = _players(con, period)
    teams = meta(con)["teams"]
    totals = {t["team_key"]: _team_totals(recs, t["team_key"]) for t in teams}

    # Rank every team per category; 1 is best, and low turnovers rank first.
    ranks = {}
    for cat in CATEGORIES:
        k = cat["key"]
        vals = [(tk, tot[k]) for tk, tot in totals.items() if tot[k] is not None]
        vals.sort(key=lambda x: x[1], reverse=not cat.get("neg"))
        ranks[k] = {tk: i + 1 for i, (tk, _) in enumerate(vals)}

    rows = []
    for t in teams:
        tk = t["team_key"]
        row = dict(t)
        row["totals"] = totals[tk]
        row["ranks"] = {k: ranks[k].get(tk) for k in ranks}
        placed = [r for r in row["ranks"].values() if r]
        row["mean_rank"] = round(sum(placed) / len(placed), 2) if placed else None
        rows.append(row)
    return {"teams": rows, "period": period, "categories": CATEGORIES}


def compare(con, a: str, b: str, period: str = "season") -> dict:
    """
    Two teams side by side, category by category. `a` and `b` are team keys.

    Each category carries both totals and an `edge` of "a", "b", "tie", or None
    where either side has no reading, and `score` counts the categories each
    would take. Like `standings` this compares roster shape, with no simulation
    and so no notion of how likely the edge is to hold in a given week.
    """
    recs = _players(con, period)
    ta, tb = _team_totals(recs, a), _team_totals(recs, b)
    names = {t["team_key"]: t["name"] for t in meta(con)["teams"]}

    cats = []
    for cat in CATEGORIES:
        k = cat["key"]
        va, vb = ta[k], tb[k]
        if va is None or vb is None:
            edge = None
        elif va == vb:
            edge = "tie"
        else:
            edge = "a" if beats(va, vb, cat) else "b"
        cats.append({**cat, "a": va, "b": vb, "edge": edge})

    return {
        "a": {"team_key": a, "name": names.get(a), **ta},
        "b": {"team_key": b, "name": names.get(b), **tb},
        "categories": cats,
        "score": {"a": sum(1 for c in cats if c["edge"] == "a"),
                  "b": sum(1 for c in cats if c["edge"] == "b")},
        "period": period,
    }


def keeper_board(con) -> dict:
    """
    The Yahoo redraft board reconciled with the composite dynasty ranking.

    `players` is every row of `v_redraft_vs_dynasty` that matched both sides,
    each stamped with the roster it sits on. `trios` is every team's three
    keepers — its top three players by composite score — ranked by the sum,
    with each keeper's redraft and blended rank carried through. `unmatched`
    lists redraft names the dynasty composite has no row for.

    `v_redraft_vs_dynasty` is hand-loaded (see `fantasy.redraft`), so this
    raises with the reload command rather than an opaque SQL error when the
    view is absent — a fresh database has no board until that module runs.
    """
    exists = con.execute(
        "select count(*) from duckdb_views() where view_name = 'v_redraft_vs_dynasty'"
    ).fetchone()[0]
    if not exists or con.execute("select count(*) from redraft_ranks").fetchone()[0] == 0:
        raise RuntimeError(
            "No redraft board loaded. Run `fantasy rankings redraft load` to "
            "write redraft_ranks and rebuild v_redraft_vs_dynasty.")
    if con.execute("select count(*) from v_composite_rankings").fetchone()[0] == 0:
        raise RuntimeError(
            "No dynasty composite yet, so the redraft board has nothing to "
            "reconcile against. Run `fantasy rankings pull <source>` for at least "
            "one source, then `fantasy rankings composite build`.")

    rows = con.execute("""
        with roster as (
            select r.player_key, t.name as team_name, t.manager_name,
                   coalesce(t.is_my_team, false) as mine
            from v_roster_players r
            join v_teams t on t.team_key = r.team_key
        )
        select v.player, v.redraft_rank, v.dynasty_rank, v.blended_rank,
               v.rank_gap, v.avg_pick, v.age, v.dynasty_score,
               ro.team_name, ro.manager_name, coalesce(ro.mine, false) as mine
        from v_redraft_vs_dynasty v
        left join roster ro on ro.player_key = v.player_key
        where v.redraft_rank is not null and v.dynasty_rank is not null
        order by v.blended_rank, v.dynasty_rank
    """).fetchall()
    keys = [d[0] for d in con.description]
    players = [dict(zip(keys, r)) for r in rows]
    for p in players:
        p["blended_rank"] = round(p["blended_rank"], 1)
        p["age"] = round(p["age"], 1) if p["age"] is not None else None

    unmatched = [r[0] for r in con.execute("""
        select r.player_name
        from redraft_ranks r
        left join v_composite_rankings c using (player_name_key)
        where c.player_name_key is null
        order by r.redraft_rank
    """).fetchall()]

    # Each team's three keepers: top three by composite score. No hypothetical
    # holds — this is the plain default, ranked by the score sum.
    krows = con.execute("""
        select t.team_key, t.name, t.manager_name, coalesce(t.is_my_team, false) as mine,
               c.player_name, c.rank as dyn_rank, c.score, c.age,
               row_number() over (partition by t.team_key order by c.rank) as slot
        from v_roster_players r
        join v_teams t on t.team_key = r.team_key
        join v_composite_rankings c on c.player_key = r.player_key
        qualify slot <= 3
    """).fetchall()
    by_team: dict = {}
    for tk, name, mgr, mine, pname, dyn_rank, score, age, slot in krows:
        t = by_team.setdefault(tk, {"team": name, "manager": mgr, "mine": mine, "keepers": []})
        t["keepers"].append({"name": pname, "dynasty_rank": dyn_rank,
                             "score": round(score, 1),
                             "age": round(age, 1) if age is not None else None})
    rd_by_name = {p["player"]: p for p in players}
    trios = []
    for t in by_team.values():
        for k in t["keepers"]:
            hit = rd_by_name.get(k["name"])
            k["redraft_rank"] = hit["redraft_rank"] if hit else None
            k["blended_rank"] = hit["blended_rank"] if hit else None
        t["trio_score"] = round(sum(k["score"] for k in t["keepers"]), 1)
        trios.append(t)
    trios.sort(key=lambda t: -t["trio_score"])

    return {
        "players": players,
        "trios": trios,
        "unmatched": unmatched,
        "counts": {"matched": len(players), "unmatched": len(unmatched)},
    }


# Every append-only sequence the store keeps, in the order `fantasy status`
# prints them. Each is stamped and resolved independently — a stale schedule
# and a fresh league snapshot coexist happily — so freshness is per-sequence
# and there is no single "last updated" to report. `subject` is the column that
# says *what* was pulled: a league key, a source name, a season.
SEQUENCES = [
    ("league", "pulls", "pull_id", "league_key", "pulled_at"),
    ("rankings", "ranking_pulls", "ranking_pull_id", "source", "pulled_at"),
    ("schedule", "nba_schedule_pulls", "pull_id", "season", "pulled_at"),
    ("seasons", "nba_season_pulls", "pull_id", "season", "pulled_at"),
    # Derived rather than pulled — nothing here comes off the wire — but
    # stamped and resolved the same way, and it goes stale against the ranking
    # pulls underneath it, so it belongs in the same freshness picture.
    ("composite", "composite_runs", "run_id", "kind", "computed_at"),
]


def store_status(con) -> list[dict]:
    """
    The newest entry in each append-only sequence, per subject.

    One row per (sequence, subject) — per league, per ranking source, per
    season — because that is the grain at which each sequence actually goes
    stale: three of the five open a row per subject, so a single "last pulled"
    would hide a season that failed while its siblings succeeded.

    Newest, not newest *successful*: a sequence whose last attempt failed is
    exactly what this is for, and reporting the older success behind it would
    hide that.

    A sequence whose table is missing is reported as absent rather than raised
    on: a database written before that sequence existed picks the table up on
    its next pull, and saying so is more useful than a SQL error.
    """
    have = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main'").fetchall()}

    out = []
    for name, table, id_col, subject_col, time_col in SEQUENCES:
        if table not in have:
            out.append({"sequence": name, "table": table, "present": False,
                        "entries": []})
            continue
        rows = con.execute(f"""
            select {subject_col}, {id_col}, {time_col}, status, note
            from {table}
            qualify row_number() over (
                partition by {subject_col} order by {id_col} desc) = 1
            order by {subject_col}
        """).fetchall()
        out.append({
            "sequence": name, "table": table, "present": True,
            "entries": [
                {"subject": subject, "id": eid, "at": at, "status": status,
                 "note": note}
                for subject, eid, at, status, note in rows
            ],
        })
    return out
