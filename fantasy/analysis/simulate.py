"""
Monte Carlo engine.

Every player is drawn **once**, into a (sims x players) column per category.
A lineup is then just a set of columns to add up, so swapping a free agent in
for a bench player costs one vector subtract and one add instead of a fresh
simulation. That makes a 350-way add/drop search affordable, and because every
candidate is scored against the same random draws the comparisons between them
carry no sampling noise of their own — only the difference is being measured.

A week is built as:

    games      ~ Binomial(n_slots, p_play)              per player, per sim
    usage      ~ Gamma(mean 1, cv from the sample size behind the rate)
    counting   ~ Gamma(mean games*usage*rate, var games*usage*spread)
    attempts   ~ Gamma, then makes ~ Binomial(attempts, shooting form)

Usage is one draw shared across a player's categories, so points, rebounds and
assists rise and fall together the way minutes make them.
"""
from dataclasses import dataclass

import numpy as np

from ..query import beats
from .projection import ATTEMPT_CV, COUNTING, RATE_PAIRS, SPREAD, Player

# Week-to-week shooting form, as the number of shots' worth of confidence we
# have in a player's percentage. Lower means streakier.
SHOOTING_ESS = 400.0

# Which categories are scored, and which of them invert, is a property of the
# league rather than of this module — see `fantasy.analysis.rules`. Every
# comparison below takes that list explicitly rather than assuming the nine
# standard categories, and defers to `query.beats` for which side of one wins.


@dataclass
class Draws:
    """Simulated weekly output for every player, one column each."""
    index: dict[str, int]           # player key -> its column in every array
    totals: dict[str, np.ndarray]   # category or makes/attempts -> (sims, players)
    sims: int

    def columns(self, player_keys) -> np.ndarray:
        """
        Column indices for a set of player keys, in the order given.

        Keys this draw does not know are skipped rather than raising, so a
        lineup can be described loosely; callers that need every player to be
        present check the length of what comes back.
        """
        return np.array([self.index[k] for k in player_keys if k in self.index],
                        dtype=np.intp)


def _gamma(rng, mean: np.ndarray, var: np.ndarray) -> np.ndarray:
    """Gamma draws matched to a mean and variance, tolerating a zero mean."""
    ok = mean > 0
    shape = np.zeros_like(mean)
    scale = np.ones_like(mean)
    np.divide(mean * mean, var, out=shape, where=ok)
    np.divide(var, mean, out=scale, where=ok)
    return rng.gamma(shape, scale).astype(np.float32)


def draw(players: list[Player], sims: int = 10000, seed: int | None = 0) -> Draws:
    """
    Simulate `sims` weeks for every player in `players`.

    `seed` fixes the generator, which is what makes two candidate rosters
    comparable: pass the same seed and the same player list and every lineup is
    scored against identical weeks. `seed=None` draws fresh randomness instead,
    which is how to check that a result is not an artefact of one seed. Raises
    `ValueError` on an empty player list.
    """
    rng = np.random.default_rng(seed)
    n = len(players)
    if n == 0:
        raise ValueError("nothing to simulate")

    p_play = np.array([p.p_play for p in players])
    n_slots = np.array([p.n_slots for p in players])
    games = rng.binomial(n_slots, p_play, size=(sims, n)).astype(np.float32)

    # One usage factor per player per week, shared by all their categories.
    cv = np.array([p.usage_cv() for p in players], dtype=np.float32)
    usage = rng.gamma(1.0 / cv**2, cv**2, size=(sims, n)).astype(np.float32)
    exposure = games * usage          # effective games at the projected rate

    totals: dict[str, np.ndarray] = {}
    for cat in COUNTING:
        rate = np.array([p.rates[cat] for p in players], dtype=np.float32)
        per_game_var = rate + (SPREAD[cat] * rate) ** 2
        totals[cat] = _gamma(rng, exposure * rate, games * per_game_var)

    for cat, (made, att) in RATE_PAIRS.items():
        rate = np.array([p.rates[att] for p in players], dtype=np.float32)
        attempts = _gamma(rng, exposure * rate,
                          games * (rate + (ATTEMPT_CV * rate) ** 2))
        pct = np.array([getattr(p, f"{cat}_pct") or 0.0 for p in players],
                       dtype=np.float64)
        # Shooting form wanders week to week around the projected percentage.
        form = np.where(
            pct > 0,
            rng.beta(np.maximum(pct * SHOOTING_ESS, 1e-6),
                     np.maximum((1 - pct) * SHOOTING_ESS, 1e-6), size=(sims, n)),
            0.0,
        )
        totals[att] = attempts
        totals[made] = rng.binomial(np.rint(attempts).astype(np.int64),
                                    form).astype(np.float32)

    keys = [p.player_key for p in players]
    return Draws(index={k: i for i, k in enumerate(keys)},
                 totals=totals, sims=sims)


def team_week(draws: Draws, columns: np.ndarray) -> dict[str, np.ndarray]:
    """
    Weekly category totals for a lineup, one value per simulation.

    Percentages are pooled over the lineup's real makes and attempts rather
    than averaged across players, which is how Yahoo scores them.
    """
    out = {c: draws.totals[c][:, columns].sum(axis=1) for c in COUNTING}
    for cat, (made, att) in RATE_PAIRS.items():
        m = draws.totals[made][:, columns].sum(axis=1)
        a = draws.totals[att][:, columns].sum(axis=1)
        out[cat] = np.divide(m, a, out=np.zeros_like(a), where=a > 0)
        out[made], out[att] = m, a
    return out


def swap(week: dict[str, np.ndarray], draws: Draws,
         drop: int | None, add: int | None) -> dict[str, np.ndarray]:
    """
    A lineup's totals with one player replaced, without re-simulating.

    `drop` and `add` are **column indices**, not player keys — take them from
    `draws.index[player_key]`. Either may be `None` to leave that side of the
    swap alone: `add=None` prices what a lineup loses by dropping someone, and
    `drop=None` what it gains from a free roster spot.
    """
    out = {}
    for c in COUNTING + [m for pair in RATE_PAIRS.values() for m in pair]:
        col = week[c]
        if drop is not None:
            col = col - draws.totals[c][:, drop]
        if add is not None:
            col = col + draws.totals[c][:, add]
        out[c] = col
    for cat, (made, att) in RATE_PAIRS.items():
        a = out[att]
        out[cat] = np.divide(out[made], a, out=np.zeros_like(a), where=a > 0)
    return out


def category_probs(a: dict, b: dict, categories: list[dict]) -> dict[str, dict]:
    """
    Win/tie/loss probability per category for lineup `a` against `b`.

    Keyed by category, each value a dict of `p_win`, `p_tie`, `p_loss` and the
    mean and standard deviation of each side's weekly total (`a_mean`, `a_sd`,
    `b_mean`, `b_sd`) — the totals in the category's own units, so a rate
    category reports a percentage and a counting one a weekly count.
    """
    out = {}
    for cat in categories:
        key = cat["key"]
        va, vb = a[key], b[key]
        wins = beats(va, vb, cat)
        ties = va == vb
        out[key] = {
            "p_win": float(wins.mean()),
            "p_tie": float(ties.mean()),
            "p_loss": float(1.0 - wins.mean() - ties.mean()),
            "a_mean": float(va.mean()), "a_sd": float(va.std()),
            "b_mean": float(vb.mean()), "b_sd": float(vb.std()),
        }
    return out


def cats_won(a: dict, b: dict, categories: list[dict]) -> np.ndarray:
    """Categories won per simulation — the head-to-head score."""
    total = np.zeros(len(a[categories[0]["key"]]), dtype=np.float32)
    for cat in categories:
        total += beats(a[cat["key"]], b[cat["key"]], cat)
    return total


def matchup_summary(a: dict, b: dict, categories: list[dict]) -> dict:
    """
    Expected score and win probability for one head-to-head week.

    Returns `expected_cats_won` (the mean of the score, not a rounded count),
    `p_win`/`p_tie`/`p_loss` over the whole matchup, `n_categories`, and
    `score_distribution` — categories won mapped to the share of simulations
    that landed there, which is where a bimodal week shows up that a mean hides.
    """
    won = cats_won(a, b, categories)
    lost = cats_won(b, a, categories)
    n = len(categories)
    return {
        "expected_cats_won": float(won.mean()),
        "p_win": float((won > lost).mean()),
        "p_tie": float((won == lost).mean()),
        "p_loss": float((won < lost).mean()),
        "score_distribution": {int(k): float(v) / len(won) for k, v in
                               zip(*np.unique(won, return_counts=True))},
        "n_categories": n,
    }
