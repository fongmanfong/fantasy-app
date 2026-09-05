"""
Per-player weekly projections.

The snapshot holds season/last_30/last_14/last_7 splits as *totals* plus games
played. That is enough to estimate a per-game rate for every category, but not
game logs, so nothing here can measure a player's real variance directly.
Instead each category gets a calibrated per-game variance model
(:data:`SPREAD`) and every player carries a usage factor whose spread widens as
the sample behind their rate shrinks. Both are consumed by
:mod:`fantasy.analysis.simulate`.

Everything is a pure function of an open connection, so a projection set can be
built once and reused across a matchup, a waiver search, or a REPL session.
"""
from dataclasses import dataclass, field

import duckdb

from ..query import latest_pull, _names

# Counting categories, plus the makes/attempts pairs behind FG% and FT%.
COUNTING = ["pts", "reb", "ast", "stl", "blk", "tpm", "tov"]
ATTEMPTS = ["fgm", "fga", "ftm", "fta"]
RATE_PAIRS = {"fg": ("fgm", "fga"), "ft": ("ftm", "fta")}

# Recency weights, applied per game played in each window. The windows nest —
# last week's games are also in the season total — so this is a recency-weighted
# estimator rather than a partition of the season.
PERIOD_WEIGHTS = {"season": 1.0, "last_30": 1.5, "last_14": 2.0, "last_7": 2.5}

# Per-game spread for each counting category, as Var = mean + (cv * mean)**2:
# a Poisson floor for the rare events plus a proportional term that dominates
# for volume stats. Calibrated so a 20 ppg scorer lands near sd 8, an 8 rpg
# rebounder near sd 3.7, and a 1.0 bpg shot-blocker near sd 1.05.
SPREAD = {"pts": 0.35, "reb": 0.32, "ast": 0.38, "stl": 0.50,
          "blk": 0.50, "tpm": 0.45, "tov": 0.40}
# Shot attempts swing much less than the makes they produce.
ATTEMPT_CV = 0.22

# Week-to-week role and minutes drift, shared across a player's categories so
# they move together. Added in quadrature with 1/sqrt(games behind the rate),
# which is what makes a 9-game sample project less confidently than a 70-game one.
USAGE_CV = 0.12

# Chance a player is available for a given scheduled game, by Yahoo status.
# NA covers players who are not on an NBA roster at all, so they are close to
# useless without being formally ruled out.
AVAILABILITY = {"Healthy": 1.0, "GTD": 0.80, "P": 0.90, "Q": 0.80, "D": 0.60,
                "O": 0.0, "INJ": 0.0, "NA": 0.20, "IL": 0.0}

# Fallback for a team `team_schedule()` has no data for (an unpulled schedule,
# or a player between NBA teams) — the old league-wide guess, used only there.
GAMES_PER_WEEK = 3.5
SCHEDULE_SLOTS = 4


@dataclass
class Player:
    """One player's projected per-game production and availability."""
    player_key: str
    name: str
    team_key: str | None
    nba: str | None
    status: str | None
    positions: list[str]
    selected_position: str | None
    is_free_agent: bool
    gp: float                      # season games played
    n_eff: float                   # recency-weighted games behind the rates
    p_play: float                  # chance of appearing in a scheduled game
    n_slots: int = SCHEDULE_SLOTS  # weekly trials `p_play` is drawn against
    rates: dict[str, float] = field(default_factory=dict)   # per-game means
    fg_pct: float | None = None
    ft_pct: float | None = None

    @property
    def on_il(self) -> bool:
        """Parked on the injured list, so accruing nothing this week."""
        return self.selected_position == "IL"

    def usage_cv(self) -> float:
        """Spread of this player's usage factor: role drift plus sample error."""
        return (USAGE_CV ** 2 + 1.0 / max(self.n_eff, 1.0)) ** 0.5


def _split_totals(con, pull_id: int) -> dict:
    """{(player_key, period): {stat: total}} for every period in the snapshot."""
    n = _names(con, pull_id)
    wanted = {
        "GP": "gp", "PTS": "pts", "REB": "reb", "AST": "ast", "ST": "stl",
        "BLK": "blk", n["tpm"]: "tpm", "TO": "tov",
        n["fgm"]: "fgm", n["fga"]: "fga", n["ftm"]: "ftm", n["fta"]: "fta",
    }
    rows = con.execute(
        "select player_key, stat_period, stat_name, value from v_player_stats "
        "where stat_name in ({})".format(", ".join("?" * len(wanted))),
        list(wanted),
    ).fetchall()

    out: dict = {}
    for player_key, period, stat_name, value in rows:
        out.setdefault((player_key, period), {})[wanted[stat_name]] = value
    return out


def _blend(splits: dict, player_key: str, periods: list[str]) -> tuple[dict, float, float]:
    """
    Recency-weighted per-game rates for one player.

    Returns (rates, season games played, effective games). A window the player
    missed entirely contributes nothing rather than dragging the rate to zero.
    """
    num = {k: 0.0 for k in COUNTING + ATTEMPTS}
    denom = 0.0
    used_weights = [0.0]
    season_gp = 0.0

    for period in periods:
        row = splits.get((player_key, period))
        if not row:
            continue
        gp = row.get("gp") or 0.0
        if period == "season":
            season_gp = gp
        if gp <= 0:
            continue
        w = PERIOD_WEIGHTS.get(period, 1.0)
        used_weights.append(w)
        denom += w * gp
        for k in num:
            num[k] += w * (row.get(k) or 0.0)

    if denom <= 0:
        return {}, season_gp, 0.0

    rates = {k: v / denom for k, v in num.items()}
    # The windows overlap, so the weighted denominator counts recent games
    # several times over. Effective sample is capped at the games actually
    # played — recency should sharpen the estimate, never invent evidence.
    n_eff = denom / max(used_weights)
    if season_gp > 0:
        n_eff = min(n_eff, season_gp)
    return rates, season_gp or n_eff, n_eff


def team_schedule(con) -> dict[str, tuple[int, float]]:
    """
    Real per-NBA-team weekly game counts, from the most recently pulled season
    in `v_nba_schedule`.

    Every team plays the same number of games over a season, so the mean is
    close to identical across teams; what differs is how the schedule clusters
    them into weeks. That is fit to a Binomial(n, p) by matching the mean and
    variance of games actually played across every Monday-Sunday week of the
    season (including bye weeks, counted as zero) — a team with a lot of
    back-to-backs gets a wider spread than one with an even schedule, instead
    of every team sharing one fixed shape.

    Returns {tricode: (n, p)}, empty if no schedule has been pulled — including
    against a snapshot older than this feature, whose read-only connection
    never ran the migration that adds `v_nba_schedule`. Callers fall back to
    (SCHEDULE_SLOTS, GAMES_PER_WEEK / SCHEDULE_SLOTS) per team.
    """
    try:
        season = con.execute(
            "select season from v_nba_schedule group by season order by season desc limit 1"
        ).fetchone()
    except duckdb.CatalogException:
        return {}
    if not season:
        return {}

    rows = con.execute("""
        with weeks as (
            select distinct date_trunc('week', game_date) as week_start
            from v_nba_schedule where season = ?
        ),
        team_games as (
            select nba_team, date_trunc('week', game_date) as week_start,
                   count(*) as games
            from v_nba_team_schedule where season = ?
            group by 1, 2
        ),
        teams as (select distinct nba_team from v_nba_team_schedule where season = ?)
        select t.nba_team, avg(coalesce(tg.games, 0)), var_pop(coalesce(tg.games, 0))
        from teams t
        cross join weeks w
        left join team_games tg on tg.nba_team = t.nba_team and tg.week_start = w.week_start
        group by 1
    """, [season[0], season[0], season[0]]).fetchall()

    out = {}
    for team, mean, var in rows:
        if not mean or mean <= 0:
            continue
        var = max(var or 0.0, 0.0)
        if var >= mean:
            # No binomial fits a spread that wide; treat the mean as fixed.
            out[team] = (max(1, round(mean)), 1.0)
            continue
        p = 1.0 - var / mean
        n = max(1, round(mean / p))
        out[team] = (n, min(1.0, mean / n))
    return out


def average_games_per_week(schedule: dict[str, tuple[int, float]]) -> float:
    """League-wide mean games/week, for contexts that want one number."""
    if not schedule:
        return GAMES_PER_WEEK
    return sum(n * p for n, p in schedule.values()) / len(schedule)


def build(con, periods: list[str] | None = None,
          games_per_week: float | None = None) -> list[Player]:
    """
    Project every rostered player and free agent in the latest snapshot.

    `periods` defaults to whichever windows the snapshot actually has. Players
    with no games in any window are dropped — there is nothing to project.

    `games_per_week` defaults to `None`, which projects each player against
    their own NBA team's real schedule (`team_schedule`). Passing a number
    overrides that with one flat rate for every team — useful for a what-if
    ("how would this look at 4 games/week") but no longer the normal path.
    """
    schedule = {} if games_per_week is not None else team_schedule(con)
    flat_p = (games_per_week if games_per_week is not None else GAMES_PER_WEEK) / SCHEDULE_SLOTS

    pull = latest_pull(con)
    available = [r[0] for r in con.execute(
        "select distinct stat_period from v_player_stats").fetchall()]
    periods = [p for p in (periods or PERIOD_WEIGHTS) if p in available]
    if not periods:
        raise RuntimeError(
            f"No usable stat periods in pull #{pull['id']}. "
            f"Snapshot has: {', '.join(available) or 'none'}.")

    splits = _split_totals(con, pull["id"])
    roster_rows = con.execute("""
        select r.player_key, p.full_name, r.team_key, p.editorial_team_abbr,
               p.status, p.positions, r.selected_position, r.is_free_agent
        from v_rosters r
        join v_players p using (league_key, player_key)
    """).fetchall()

    # How far into the season we are, used to turn games played into a
    # durability estimate. The 90th percentile is a robust stand-in for the
    # number of games each NBA team has played.
    season_gps = [row["gp"] for (_, period), row in splits.items()
                  if period == "season" and (row.get("gp") or 0) > 0]
    season_gps.sort()
    elapsed = season_gps[int(0.9 * (len(season_gps) - 1))] if season_gps else 0.0

    players = []
    for (player_key, name, team_key, nba, status, positions,
         selected_position, is_free_agent) in roster_rows:
        rates, gp, n_eff = _blend(splits, player_key, periods)
        if not rates or n_eff <= 0:
            continue

        # Games missed so far are informative but not decisive over a single
        # week, so the rate is blended halfway toward full availability. Today's
        # injury status carries the rest of the signal; keeping durability mild
        # stops the two from compounding into an implausibly low number.
        played = min(1.0, gp / elapsed) if elapsed > 0 else 1.0
        durability = 0.5 + 0.5 * played
        status_factor = 0.0 if selected_position == "IL" else \
            AVAILABILITY.get(status or "Healthy", 0.6)

        n_slots, p_slot = schedule.get(nba, (SCHEDULE_SLOTS, flat_p))

        fga, fta = rates.get("fga", 0.0), rates.get("fta", 0.0)
        players.append(Player(
            player_key=player_key, name=name, team_key=team_key, nba=nba,
            status=status, positions=list(positions or []),
            selected_position=selected_position, is_free_agent=bool(is_free_agent),
            gp=gp, n_eff=n_eff,
            p_play=min(1.0, p_slot * status_factor * durability),
            n_slots=n_slots,
            rates={k: rates.get(k, 0.0) for k in COUNTING + ATTEMPTS},
            fg_pct=(rates.get("fgm", 0.0) / fga) if fga > 0 else None,
            ft_pct=(rates.get("ftm", 0.0) / fta) if fta > 0 else None,
        ))
    return players


def by_team(players: list[Player]) -> dict[str, list[Player]]:
    """Rostered players grouped by team key, free agents excluded."""
    out: dict[str, list[Player]] = {}
    for p in players:
        if not p.is_free_agent and p.team_key:
            out.setdefault(p.team_key, []).append(p)
    return out


def actives(players: list[Player]) -> list[Player]:
    """Players who accrue stats this week: everyone not parked on IL."""
    return [p for p in players if not p.on_il]
