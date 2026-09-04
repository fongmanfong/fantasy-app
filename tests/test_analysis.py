"""
The simulation math, with no database and no network.

Players are built by hand so each check pins one behaviour: the recency blend,
the mean/variance of a drawn week, the swap shortcut agreeing with a full
recompute, and the lineup-legality guard.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from fantasy.analysis import projection, simulate, waiver
from fantasy.analysis.projection import Player

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


def close(label, actual, expected, tol):
    if abs(actual - expected) > tol:
        failures.append(f"{label}\n    expected: {expected} +/- {tol}\n    actual:   {actual}")


def make(key, pts=20.0, reb=5.0, ast=4.0, stl=1.0, blk=0.5, tpm=2.0, tov=2.0,
         fgm=7.0, fga=15.0, ftm=4.0, fta=5.0, p_play=0.875, gp=70.0,
         positions=("PG", "G", "Util"), slot="Util"):
    return Player(
        player_key=key, name=key, team_key="t.1", nba="LAL", status="Healthy",
        positions=list(positions), selected_position=slot, is_free_agent=False,
        gp=gp, n_eff=gp, p_play=p_play,
        rates={"pts": pts, "reb": reb, "ast": ast, "stl": stl, "blk": blk,
               "tpm": tpm, "tov": tov, "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta},
        fg_pct=fgm / fga, ft_pct=ftm / fta,
    )


# --- the recency blend --------------------------------------------------

SPLITS = {
    ("p1", "season"): {"gp": 60.0, "pts": 600.0, "fgm": 200.0, "fga": 500.0},
    ("p1", "last_7"): {"gp": 4.0, "pts": 80.0, "fgm": 20.0, "fga": 40.0},
    # A window the player missed entirely.
    ("p1", "last_14"): {"gp": 0.0, "pts": 0.0},
}

rates, gp, n_eff = projection._blend(SPLITS, "p1", ["season", "last_7", "last_14"])
# (1.0*600 + 2.5*80) / (1.0*60 + 2.5*4) = 800/70
close("hot streak pulls the rate above the season average", rates["pts"], 800 / 70, 1e-9)
check("season games reported unchanged", gp, 60.0)
close("makes and attempts blend on the same denominator",
      rates["fgm"] / rates["fga"], 250 / 600, 1e-9)
check("a missed window cannot drag the rate down", rates["pts"] > 10.0, True)
check("effective sample never exceeds games actually played", n_eff <= 60.0, True)

empty, _, n = projection._blend({}, "ghost", ["season"])
check("a player with no games projects nothing", (empty, n), ({}, 0.0))

cv_small = make("a", gp=8.0)
cv_small.n_eff = 8.0
check("a small sample projects less confidently",
      make("b", gp=70.0).usage_cv() < cv_small.usage_cv(), True)


# --- drawn weeks --------------------------------------------------------

rng = np.random.default_rng(1)
mean = np.full(20000, 12.0)
var = np.full(20000, 9.0)
g = simulate._gamma(rng, mean, var)
close("gamma draws match the requested mean", float(g.mean()), 12.0, 0.1)
close("gamma draws match the requested variance", float(g.var()), 9.0, 0.4)

zero = simulate._gamma(rng, np.zeros(10), np.zeros(10))
check("a zero mean draws zero, not a divide-by-zero", float(zero.sum()), 0.0)

team = [make(f"p{i}") for i in range(10)]
draws = simulate.draw(team, sims=6000, seed=7)
week = simulate.team_week(draws, draws.columns([p.player_key for p in team]))

# 10 players x Binomial(4, 0.875) games x 20 points.
close("weekly points track games x rate", float(week["pts"].mean()), 10 * 3.5 * 20, 25)
close("pooled FG% comes back at the players' rate", float(week["fg"].mean()), 7 / 15, 0.01)
check("percentages are pooled, not averaged",
      float(week["fgm"].mean()) / float(week["fga"].mean()) > 0.46, True)
check("a team week has real spread", float(week["pts"].std()) > 30, True)


# --- comparisons --------------------------------------------------------

strong = simulate.team_week(draws, draws.columns([p.player_key for p in team]))
weak_players = [make(f"w{i}", pts=4.0, reb=1.0, ast=1.0, stl=0.2, blk=0.1,
                     tpm=0.3, tov=4.0, fgm=1.5, fga=6.0, ftm=1.0, fta=2.0)
                for i in range(10)]
weak_draws = simulate.draw(weak_players, sims=6000, seed=8)
weak = simulate.team_week(weak_draws, weak_draws.columns(
    [p.player_key for p in weak_players]))

probs = simulate.category_probs(strong, weak)
check("a far better team wins points essentially always", probs["pts"]["p_win"] > 0.99, True)
check("turnovers are won by the lower number", probs["tov"]["p_win"] > 0.99, True)
close("probabilities sum to one",
      probs["reb"]["p_win"] + probs["reb"]["p_tie"] + probs["reb"]["p_loss"], 1.0, 1e-6)

summary = simulate.matchup_summary(strong, weak)
close("a dominant week sweeps the categories", summary["expected_cats_won"], 9.0, 0.05)
check("and wins the matchup", summary["p_win"] > 0.99, True)

mirror = simulate.matchup_summary(strong, strong)
close("a team against itself ties every category", mirror["expected_cats_won"], 0.0, 1e-6)


# --- the swap shortcut --------------------------------------------------

bench = make("bench", pts=3.0, reb=1.0, ast=0.5, positions=("C", "Util"), slot="BN")
pool = team + [bench]
pool_draws = simulate.draw(pool, sims=2000, seed=11)
full = simulate.team_week(pool_draws, pool_draws.columns([p.player_key for p in team]))
swapped = simulate.swap(full, pool_draws, drop=pool_draws.index["p0"],
                        add=pool_draws.index["bench"])
recomputed = simulate.team_week(pool_draws, pool_draws.columns(
    [p.player_key for p in team if p.player_key != "p0"] + ["bench"]))
for cat in ("pts", "reb", "tov", "fg", "ft"):
    check(f"swap matches a full recompute for {cat}",
          bool(np.allclose(swapped[cat], recomputed[cat], atol=1e-4)), True)


# --- lineup legality ----------------------------------------------------

SLOTS = [{"PG"}, {"SG"}, {"PG", "SG"}, {"SF"}, {"PF"}, {"SF", "PF"},
         {"C"}, {"C"}, None, None, None]

legal = ([make(f"g{i}", positions=("PG", "SG", "G", "Util")) for i in range(4)]
         + [make(f"f{i}", positions=("SF", "PF", "F", "Util")) for i in range(4)]
         + [make(f"c{i}", positions=("C", "Util")) for i in range(3)])
check("a balanced roster fills every slot", waiver.fills_lineup(legal, SLOTS), True)

one_centre = legal[:8] + [make("c0", positions=("C", "Util"))]
check("too few players cannot fill the lineup",
      waiver.fills_lineup(one_centre, SLOTS), False)

no_centre = [make(f"g{i}", positions=("PG", "SG", "G", "Util")) for i in range(11)]
check("a roster with no centre is rejected however deep it is",
      waiver.fills_lineup(no_centre, SLOTS), False)

check("two centres are enough for the two centre slots",
      waiver.fills_lineup(legal[:8] + [make("c0", positions=("C", "Util")),
                                       make("c1", positions=("C", "Util")),
                                       make("c2", positions=("C", "Util"))], SLOTS), True)


# --- scoring against a set of opponents ---------------------------------

score = waiver.Scorer([weak, weak])
cats, win, per_cat = score(strong)
close("scoring against identical opponents sweeps", cats, 9.0, 0.05)
check("and reports a win", win > 0.99, True)
check("per-category odds come back for every category",
      sorted(per_cat) == sorted(c["key"] for c in waiver.CATEGORIES), True)

if failures:
    print(f"FAILED ({len(failures)}):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all analysis checks passed")
