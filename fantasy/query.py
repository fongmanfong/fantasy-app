"""
Read-side queries over the latest DuckDB snapshot.

Every function takes an open connection and returns plain dicts, so the HTTP
layer is a thin shell around this module and the same calls work from a REPL.
"""

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
