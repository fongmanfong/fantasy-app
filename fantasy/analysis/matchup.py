"""
Head-to-head analysis: how one team's week is likely to score against another.

`head_to_head` answers "what are my odds in each category against this team";
`versus_field` runs the same week against all eleven opponents at once, which
is the right question when nobody is asking about a specific matchup.
"""
import numpy as np

from . import projection, rules as rules_mod, simulate


def resolve_team(con, needle: str | None) -> dict:
    """
    Find a team from a key, a team id, or part of a name or manager.

    Passing nothing gives your own team.
    """
    rows = [dict(zip(["team_key", "team_id", "name", "manager", "is_my_team"], r))
            for r in con.execute(
                "select team_key, team_id, name, manager_name, is_my_team "
                "from v_teams").fetchall()]
    if not rows:
        raise RuntimeError("No teams in the snapshot. Run `fantasy pull` first.")

    if needle is None:
        mine = [t for t in rows if t["is_my_team"]]
        if not mine:
            raise RuntimeError("No team is flagged as yours in this snapshot; "
                               "name one explicitly.")
        return mine[0]

    needle = needle.strip()
    for t in rows:
        if needle in (t["team_key"], t["team_id"]):
            return t

    lowered = needle.lower()
    hits = [t for t in rows
            if lowered in (t["name"] or "").lower()
            or lowered in (t["manager"] or "").lower()]
    if len(hits) == 1:
        return hits[0]
    if hits:
        names = ", ".join(f"{t['name']} ({t['team_id']})" for t in hits)
        raise RuntimeError(f"{needle!r} matches several teams: {names}")
    raise RuntimeError(
        f"No team matches {needle!r}. Known teams: "
        + ", ".join(f"{t['name']} ({t['team_id']})" for t in rows))


def prepare(con, periods=None, sims: int = 10000, seed: int | None = 0,
            games_per_week: float = projection.GAMES_PER_WEEK):
    """
    Read the league rules, then project and simulate every player once.

    Rules come first: a league the model cannot represent should fail before
    any work is done, not after a plausible-looking table has been printed.
    """
    rules = rules_mod.load(con, games_per_week=games_per_week)
    players = projection.build(con, periods=periods, games_per_week=games_per_week)
    draws = simulate.draw(players, sims=sims, seed=seed)
    return players, draws, rules


def lineup_columns(draws, players, team_key: str) -> np.ndarray:
    """The columns for a team's active roster: everyone not parked on IL."""
    keys = [p.player_key for p in projection.actives(players)
            if p.team_key == team_key and not p.is_free_agent]
    if not keys:
        raise RuntimeError(f"No active players found for {team_key}.")
    return draws.columns(keys)


def _category_rows(probs: dict, categories: list[dict]) -> list[dict]:
    return [{**cat, **probs[cat["key"]]} for cat in categories]


def head_to_head(con, team_a: str | None = None, team_b: str | None = None,
                 periods=None, sims: int = 10000, seed: int | None = 0,
                 games_per_week: float = projection.GAMES_PER_WEEK) -> dict:
    """
    Simulate a week between two teams.

    Returns per-category win/tie/loss probabilities, projected totals for both
    sides, and the distribution of the 9-category score.
    """
    a = resolve_team(con, team_a)
    b = resolve_team(con, team_b)
    if a["team_key"] == b["team_key"]:
        raise RuntimeError("A team cannot be benchmarked against itself.")

    players, draws, rules = prepare(con, periods, sims, seed, games_per_week)
    cats = rules.categories
    ca = lineup_columns(draws, players, a["team_key"])
    cb = lineup_columns(draws, players, b["team_key"])
    wa, wb = simulate.team_week(draws, ca), simulate.team_week(draws, cb)

    return {
        "a": a, "b": b, "rules": rules,
        "categories": _category_rows(simulate.category_probs(wa, wb, cats), cats),
        **simulate.matchup_summary(wa, wb, cats),
        "sims": sims, "games_per_week": games_per_week,
        "roster_size": {a["team_key"]: len(ca), b["team_key"]: len(cb)},
    }


def versus_field(con, team_a: str | None = None, periods=None, sims: int = 10000,
                 seed: int | None = 0,
                 games_per_week: float = projection.GAMES_PER_WEEK) -> dict:
    """One team's week run against every other team in the league."""
    a = resolve_team(con, team_a)
    players, draws, rules = prepare(con, periods, sims, seed, games_per_week)
    cats = rules.categories
    wa = simulate.team_week(draws, lineup_columns(draws, players, a["team_key"]))

    names = dict(con.execute("select team_key, name from v_teams").fetchall())
    opponents = [t for t in projection.by_team(players) if t != a["team_key"]]
    rows, per_cat = [], {c["key"]: [] for c in cats}
    for opp in opponents:
        wb = simulate.team_week(draws, lineup_columns(draws, players, opp))
        probs = simulate.category_probs(wa, wb, cats)
        summary = simulate.matchup_summary(wa, wb, cats)
        rows.append({"team_key": opp, "name": names.get(opp),
                     **{k: summary[k] for k in
                        ("expected_cats_won", "p_win", "p_tie", "p_loss")}})
        for k in per_cat:
            per_cat[k].append(probs[k]["p_win"])
    rows.sort(key=lambda r: r["p_win"])

    return {
        "a": a, "rules": rules,
        "opponents": rows,
        "categories": [{**c, "p_win": float(np.mean(per_cat[c["key"]]))}
                       for c in cats],
        "expected_cats_won": float(np.mean([r["expected_cats_won"] for r in rows])),
        "p_win": float(np.mean([r["p_win"] for r in rows])),
        "sims": sims, "games_per_week": games_per_week,
    }
