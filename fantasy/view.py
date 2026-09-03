"""Render a team's roster and category strength as a standalone HTML page."""
import json
from pathlib import Path

TEMPLATE = Path(__file__).parent / "templates" / "roster.html"

# Counting categories, as (stat name, payload key). Rates are handled separately
# because they are already percentages and must not be divided by games played.
COUNTING = [("PTS", "pts"), ("REB", "reb"), ("AST", "ast"),
            ("ST", "stl"), ("BLK", "blk"), ("__3PM__", "tpm"), ("TO", "tov")]
RATES = [("FG%", "fg"), ("FT%", "ft")]


def made_threes_name(con, pull_id: int) -> str:
    """
    Which stat name holds *made* threes in this pull.

    Rows written before the stat-map fix carry the reversed names, where "3PTA"
    is really makes. Those rows are identifiable because the legacy replay left
    `stat_id` null, while a real pull always sets it.
    """
    legacy = con.execute(
        "select count(*) = 0 from player_stats where pull_id = ? and stat_id is not null",
        [pull_id],
    ).fetchone()[0]
    return "3PTA" if legacy else "3PTM"


def build(con, team_name: str | None = None, period: str = "season") -> dict:
    league = con.execute(
        "select league_key, name, season, num_teams from v_leagues limit 1"
    ).fetchone()
    if not league:
        raise RuntimeError("No league in the database yet. Run `fantasy pull` first.")
    league_key, league_name, season, num_teams = league

    pull_id = con.execute("select pull_id from latest_pull limit 1").fetchone()[0]
    three = made_threes_name(con, pull_id)

    if team_name:
        team = con.execute(
            "select team_key, name, manager_name, wins, losses, standing "
            "from v_teams where lower(name) = lower(?)", [team_name]
        ).fetchone()
        if not team:
            names = [r[0] for r in con.execute(
                "select name from v_teams order by name").fetchall()]
            raise RuntimeError(
                f"No team named {team_name!r}. Teams in this league:\n  " + "\n  ".join(names)
            )
    else:
        team = con.execute(
            "select team_key, name, manager_name, wins, losses, standing "
            "from v_teams where is_my_team"
        ).fetchone()
        if not team:
            raise RuntimeError("No team is flagged as yours. Pass --team explicitly.")

    team_key, tname, manager, wins, losses, standing = team

    def agg(stat, key):
        return f"max(case when st.stat_name = '{stat}' then st.value end) as {key}"

    selects = ", ".join(
        [agg("GP", "gp")]
        + [agg(three if s == "__3PM__" else s, k) for s, k in COUNTING]
        + [agg(s, k) for s, k in RATES]
    )

    rows = con.execute(f"""
        select r.team_key, r.player_key, p.full_name, p.editorial_team_abbr,
               p.status, r.selected_position, {selects}
        from v_rosters r
        join v_players p using (league_key, player_key)
        join v_player_stats st using (league_key, player_key)
        where st.stat_period = ? and not r.is_free_agent
        group by 1,2,3,4,5,6
    """, [period]).fetchall()
    cols = [d[0] for d in con.description]
    recs = [dict(zip(cols, r)) for r in rows]
    recs = [r for r in recs if (r["gp"] or 0) > 0]
    if not recs:
        have = [r[0] for r in con.execute(
            "select distinct stat_period from v_player_stats order by 1").fetchall()]
        raise RuntimeError(
            f"No stats for period {period!r} in the latest pull. "
            f"Available: {', '.join(have) or 'none'}")

    for r in recs:
        for _, k in COUNTING:
            r[k] = (r[k] or 0) / r["gp"]

    # League-wide percentile context: every rostered player, this period.
    def percentile(key: str, value, lower_better: bool) -> float:
        vals = [x[key] for x in recs if x[key] is not None]
        if not vals or value is None:
            return 0.5
        below = sum(1 for v in vals if v < value) / len(vals)
        return 1 - below if lower_better else below

    players = []
    for r in recs:
        if r["team_key"] != team_key:
            continue
        p = {"name": r["full_name"], "pos": r["selected_position"],
             "nba": r["editorial_team_abbr"], "status": r["status"],
             "gp": int(r["gp"])}
        for _, k in COUNTING + RATES:
            v = r[k]
            p[k] = round(v, 3) if v is not None else None
            p[k + "_p"] = round(percentile(k, v, lower_better=(k == "tov")), 3)
        players.append(p)
    players.sort(key=lambda x: -(x["pts"] or 0))

    pulled_at, = con.execute(
        "select pulled_at from pulls where pull_id = ?", [pull_id]
    ).fetchone()

    return {
        "league": {"name": league_name, "season": season, "teams": num_teams,
                   "key": league_key},
        "team": {"name": tname, "manager": manager, "wins": wins,
                 "losses": losses, "standing": standing},
        "players": players,
        "period": period,
        "pool": len(recs),
        "pull": {"id": pull_id, "at": pulled_at.isoformat()},
        "legacy_names": three == "3PTA",
    }


def render(payload: dict) -> str:
    html = TEMPLATE.read_text()
    return (html
            .replace("__TEAM_NAME__", payload["team"]["name"])
            .replace("__DATA__", json.dumps(payload, separators=(",", ":"))))
