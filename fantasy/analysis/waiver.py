"""
Free-agent search: which add/drop actually moves the odds.

Every candidate roster is scored against the same simulated weeks as the
baseline (see :mod:`fantasy.analysis.simulate`), so a swap's reported gain is a
real difference and not two noisy numbers subtracted. The objective is expected
categories won per week — against one named opponent, or averaged over the
whole league when no opponent is given.

Drop candidates are not guessed at: every player on the roster is first priced
by what the team loses without them, and only the cheapest are offered up.
"""
import numpy as np

from ..query import beats
from . import matchup, projection, rules as rules_mod, simulate

# Slots a player can fill beyond their listed positions.
FLEX = {"G": {"PG", "SG"}, "F": {"SF", "PF"}}


def _lineup_slots(con) -> list[set | None]:
    """Active roster slots, each as the set of positions it accepts (None: any)."""
    rows = con.execute(
        "select position, count from v_roster_positions").fetchall()
    slots: list[set | None] = []
    for position, count in rows:
        if rules_mod.is_bench(position):
            continue
        for _ in range(count or 0):
            if position in ("Util", "UTIL"):
                slots.append(None)
            else:
                slots.append(FLEX.get(position, {position}))
    return slots


def fills_lineup(players: list, slots: list[set | None]) -> bool:
    """
    Whether a roster can legally fill every active slot.

    Kuhn's algorithm for maximum bipartite matching — with three Util slots and
    two flex spots the constraint almost never binds, but it is what stops a
    search from recommending you drop your only centre.
    """
    if len(players) < len(slots):
        return False
    eligible = [set(p.positions or []) for p in players]
    match: dict[int, int] = {}          # player index -> slot index

    def assign(slot: int, seen: set) -> bool:
        for i, positions in enumerate(eligible):
            accepts = slots[slot]
            if accepts is not None and not (positions & accepts):
                continue
            if i in seen:
                continue
            seen.add(i)
            if i not in match or assign(match[i], seen):
                match[i] = slot
                return True
        return False

    return all(assign(s, set()) for s in range(len(slots)))


class Scorer:
    """
    Scores a candidate week against a fixed set of opponents.

    Deliberately two-dimensional where :func:`fantasy.analysis.simulate.cats_won`
    is one: the opponents' weeks are stacked into a (opponents x sims) array so
    a candidate roster is measured against the whole league in one pass. That is
    what makes a several-hundred-way add/drop search affordable.
    """

    def __init__(self, opponent_weeks: list[dict], categories: list[dict]):
        """`opponent_weeks` are `simulate.team_week` results, one per opponent."""
        self.n = len(opponent_weeks)
        self.categories = categories
        self.opp = {c["key"]: np.stack([w[c["key"]] for w in opponent_weeks])
                    for c in categories}

    def __call__(self, week: dict) -> tuple[float, float, dict]:
        """Returns (expected categories won, win probability, per-category odds)."""
        won = np.zeros_like(next(iter(self.opp.values())))
        lost = np.zeros_like(won)
        per_cat = {}
        for cat in self.categories:
            k = cat["key"]
            va, vb = week[k], self.opp[k]
            win, lose = beats(va, vb, cat), beats(vb, va, cat)
            won += win
            lost += lose
            per_cat[k] = float(win.mean())
        return float(won.mean()), float((won > lost).mean()), per_cat


def _describe(p: projection.Player) -> dict:
    """The player fields a caller needs to name a move, without the projection."""
    return {"player_key": p.player_key, "name": p.name, "nba": p.nba,
            "positions": p.positions, "status": p.status, "gp": round(p.gp, 1),
            "slot": p.selected_position}


def add_drop(con, team: str | None = None, opponent: str | None = None,
             periods=None, sims: int = 4000, seed: int | None = 0,
             games_per_week: float | None = None,
             max_drops: int = 6, top: int = 15, min_gp: float = 5.0) -> dict:
    """
    Rank every legal free-agent pickup by how much it improves the week.

    `team` is whose roster to improve (yours by default) and `opponent` narrows
    the objective to one team; left out, a swap is judged on how it plays
    against the league as a whole. `max_drops` caps how many of your own
    players are considered droppable — the least valuable ones, priced by what
    the team gives up without them. `top` caps the returned move lists,
    `min_gp` excludes free agents with too little sample to project, and
    `periods`, `sims`, `seed` and `games_per_week` are handed to
    `matchup.prepare` unchanged.

    Returns `team` and `rules`; `opponents` the move was scored against;
    `baseline` (the roster as it stands, as `expected_cats_won`, `p_win` and
    per-category win rates); `moves`, the best add/drop pairs, each carrying
    `add`, `drop`, `expected_cats_won`, `delta_cats`, `p_win`, `delta_p_win`,
    per-category deltas and the `drop_cost`; `best_by_player`, the same list cut
    to one row per free agent; `drop_candidates` with their `cost`;
    `considered` (how many free agents and pairs were searched); and `sims`,
    `games_per_week` and `categories`.

    **`delta_cats` is the number to compare between candidates**, not to quote
    on its own — every candidate is scored against the same draws, so the
    ordering is far more stable than any single figure.
    """
    known = matchup.teams(con)
    me = matchup.resolve_team(con, team, known)
    my_key = me["team_key"]

    players, draws, rules = matchup.prepare(con, periods, sims, seed, games_per_week)
    rostered = projection.by_team(players)
    if my_key not in rostered:
        raise RuntimeError(f"No rostered players found for {me['name']}.")

    mine = projection.actives(rostered[my_key])
    my_cols = draws.columns([p.player_key for p in mine])
    baseline_week = simulate.team_week(draws, my_cols)

    opponents = ([matchup.resolve_team(con, opponent, known)]
                 if opponent else
                 [matchup.resolve_team(con, k, known) for k in rostered if k != my_key])
    if not opponents:
        raise RuntimeError("No opponents to measure against.")
    score = Scorer([
        simulate.team_week(draws, matchup.lineup_columns(draws, players, o["team_key"]))
        for o in opponents], rules.categories)

    base_cats, base_win, base_per_cat = score(baseline_week)

    # Price every roster spot by what the team gives up without it, then offer
    # up only the cheapest as drop candidates.
    priced = []
    for p in mine:
        col = draws.index[p.player_key]
        cats, _, _ = score(simulate.swap(baseline_week, draws, drop=col, add=None))
        priced.append((base_cats - cats, p))
    priced.sort(key=lambda x: x[0])
    drops = priced[:max_drops]

    slots = _lineup_slots(con)
    candidates = [p for p in players
                  if p.is_free_agent and p.gp >= min_gp and p.p_play > 0]

    # The roster minus each drop candidate is fixed across the whole search, so
    # build it once per drop rather than once per (candidate, drop) pair.
    without = {drop.player_key: [p for p in mine if p.player_key != drop.player_key]
               for _, drop in drops}

    results = []
    for add in candidates:
        add_col = draws.index[add.player_key]
        for value, drop in drops:
            if not fills_lineup(without[drop.player_key] + [add], slots):
                continue
            week = simulate.swap(baseline_week, draws,
                                 drop=draws.index[drop.player_key], add=add_col)
            cats, win, per_cat = score(week)
            results.append({
                "add": _describe(add), "drop": _describe(drop),
                "expected_cats_won": cats, "delta_cats": cats - base_cats,
                "p_win": win, "delta_p_win": win - base_win,
                "categories": {k: per_cat[k] - base_per_cat[k] for k in per_cat},
                "drop_cost": value,
            })

    results.sort(key=lambda r: -r["delta_cats"])
    best_per_add: dict[str, dict] = {}
    for r in results:
        best_per_add.setdefault(r["add"]["player_key"], r)

    return {
        "team": me, "rules": rules,
        "opponents": [{"team_key": o["team_key"], "name": o["name"]}
                      for o in opponents],
        "baseline": {"expected_cats_won": base_cats, "p_win": base_win,
                     "categories": base_per_cat},
        "moves": results[:top],
        "best_by_player": sorted(best_per_add.values(),
                                 key=lambda r: -r["delta_cats"])[:top],
        "drop_candidates": [{**_describe(p), "cost": v} for v, p in drops],
        "considered": {"free_agents": len(candidates), "pairs": len(results)},
        "sims": sims, "games_per_week": rules.games_per_week,
        "categories": rules.categories,
    }
