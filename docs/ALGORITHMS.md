# Algorithms

How `fantasy matchup` and `fantasy waivers` turn a snapshot into probabilities.

Everything here follows from one constraint: **the snapshot holds totals, not
game logs.** Yahoo gives four windows per player — season, last 30, last 14,
last 7 days — each a bag of counting totals plus games played. There is no
per-game history to measure a player's real variance from, so that gap is
filled with an explicit, documented parameter rather than a hidden default,
and it is listed under [Limitations](#limitations). A second gap — how many
games each team actually plays in a week — used to be filled the same way,
but is now read from the real NBA schedule (`team_schedule` in
[projection.py](../fantasy/analysis/projection.py)); see
[Games](#games) below.

The pipeline is five stages, preceded by a rules check:

| Stage | Module | Produces |
|---|---|---|
| 0. League rules | `rules.py` | what is scored, and what had to be assumed |
| 1. Rate estimation | `projection.py` | a per-game mean for each category |
| 2. Availability | `projection.py` | the chance a player appears in a given game |
| 3. Week simulation | `simulate.py` | `sims` weekly totals per player |
| 4. Matchup scoring | `simulate.py`, `matchup.py` | win probability per category |
| 5. Waiver search | `waiver.py` | ranked add/drops |

---

## 0. League rules

`rules.load` ([rules.py](../fantasy/analysis/rules.py))

Every run starts here, before any simulation, because a league the model cannot
represent should fail before it prints a plausible-looking table rather than
after. Rules are re-derived from the snapshot on each run, so a settings change
or a second league is picked up automatically — nothing about the league is
baked into the code.

**Read from the snapshot:**

- **Which categories are scored**, from `v_stat_categories`, filtering rows
  flagged `is_only_display` (Yahoo lists `FGM/A` and `FTM/A` as display-only).
  The mapping is keyed on Yahoo's **`stat_id`**, never the stored name —
  snapshots taken before the stat-map fix have makes and attempts transposed,
  so `stat_id` is the only stable identifier.
- **Which category inverts**, from `sort_order` (`0` means a lower number wins).
  Snapshots that predate storing it fall back to turnovers, and say so.
- **Roster slots**, from `v_roster_positions`.

**Refused rather than approximated:**

- A league that is not head-to-head categories. Scoring a week by category wins
  is meaningless in a points or rotisserie league, so `scoring_type != "head"`
  raises.
- A league scoring anything the simulator has no quantity for — double-doubles,
  A/T ratio, minutes. Every scored category has to be simulated for the
  majority threshold to mean anything, so a partial answer would be a wrong
  answer.

**Assumed, and printed above every result:**

| Assumption | Why it is not in the snapshot |
|---|---|
| daily lineups | Yahoo's roster-change frequency is not pulled |
| perfect management | an idealisation, not a setting |
| unlimited adds | max acquisitions are not pulled |

Games per team is **no longer on this list** — it is read from the pulled NBA
schedule (`fantasy schedule pull`) and fit per team, falling back to a flat
3.5/week only when no schedule has been pulled, or when `--games` overrides it
on purpose.

`fantasy rules` prints the whole table with sources and notes. The one-line
version appears above every matchup and waiver run — league rules change, and a
snapshot will not notice, so the assumptions are repeated rather than left in
this document.

---

## 1. Rate estimation — the recency blend

`projection._blend` ([projection.py:104](../fantasy/analysis/projection.py))

For a player and a category, the per-game rate is a weighted ratio of totals to
games, taken across every window:

```
              Σ_w  weight(w) · total(category, w)
    rate  =  ──────────────────────────────────────
                   Σ_w  weight(w) · games(w)
```

with `PERIOD_WEIGHTS = {season: 1.0, last_30: 1.5, last_14: 2.0, last_7: 2.5}`.

Three properties fall out of writing it this way:

**The weight is per game, not per window.** A window's influence is
`weight × games`, so a four-game last-7 window moves the estimate about as much
as its four games deserve. Weighting the *windows* equally would let a hot
three-game stretch outvote sixty games of season.

**Missed windows cost nothing.** A window with zero games contributes zero to
both numerator and denominator and drops out. This matters: a player returning
from a two-week absence has `last_7 = last_14 = 0`, and a naive average over
windows would project him at a third of his real rate.

**Makes and attempts share a denominator.** FG% is not blended directly. `fgm`
and `fga` are blended separately and divided, so the result is a true weighted
shooting percentage rather than an average of percentages.

*Worked example* — 60 games / 600 pts on the season, 4 games / 80 pts in the
last week, nothing in the last 14 (injured, then returned):

```
    rate = (1.0·600 + 2.5·80) / (1.0·60 + 2.5·4) = 800 / 70 = 11.4 ppg
```

against a 10.0 season average — the hot week pulls it up, but not to 20.

### Effective sample size

The windows **nest**: last week's games are also inside the season total, so
the weighted denominator counts recent games several times over. Left alone it
reports 92 games behind a 33-game player. So it is capped:

```
    n_eff = min( Σ weight(w)·games(w) / max weight ,  season games )
```

Recency is allowed to sharpen an estimate, never to invent evidence. `n_eff`
feeds the usage spread in stage 3, which is the only place it is used — it is a
confidence measure, not a rate.

> In an off-season snapshot Yahoo returns full-season figures for every window,
> so all four are identical and the blend is a no-op. It only starts doing work
> mid-season.

---

## 2. Availability

`projection.build` ([projection.py:144](../fantasy/analysis/projection.py))

Two different things make a player miss games: he is hurt *right now*, and he
is the kind of player who misses games. Yahoo's status field carries the first,
games played carries the second.

```
    p_play = p_slot · status_factor · durability
    durability = 0.5 + 0.5 · min(1, games_played / games_elapsed)
```

`p_slot` is a per-scheduled-game probability, and it comes from the player's
own NBA team rather than a league constant — see [Games](#games) for where it
is fit.

`status_factor` comes from the `AVAILABILITY` table
([projection.py:46](../fantasy/analysis/projection.py)):

| Status | Factor | |
|---|---|---|
| `Healthy` | 1.00 | |
| `P` (probable) | 0.90 | |
| `GTD` / `Q` | 0.80 | game-time decisions mostly play |
| `D` (doubtful) | 0.60 | |
| `O`, `INJ`, or an IL slot | 0.00 | |
| `NA` | 0.20 | not on an NBA roster — nearly useless, but not formally ruled out |

`games_elapsed` is the 90th percentile of season games played across the
league, a robust stand-in for how many games each NBA team has played (the max
would be knocked off by a single ironman, the mean by injured players).

Durability is deliberately **blended halfway toward full availability**, not
used raw. The two terms multiply, and both are injury signals, so raw durability
would double-count: a GTD player who has played 33 of 82 games would come out at
`0.80 × 0.40 = 32%` available, which is far too harsh for a single week. Softened,
he lands at `0.80 × 0.70 = 56%`, and a healthy 72-game player at 94% — both
before `p_slot`, which scales all of them to a per-scheduled-game number; see
the next stage for where that comes from.

---

## 3. Week simulation

`simulate.draw` ([simulate.py:60](../fantasy/analysis/simulate.py))

Each player's week is built from four random variables. Every one is drawn as a
`(sims × players)` array, so the whole league is simulated in one pass.

```
    G  ~ Binomial(n_slots, p_play)                 games played
    U  ~ Gamma(mean 1, cv = usage_cv)             usage / role
    X  ~ Gamma(mean G·U·rate, var G·v)            counting stat
    A  ~ Gamma(mean G·U·rate, var G·v)            shot attempts
    f  ~ Beta(pct·400, (1-pct)·400)               shooting form
    M  ~ Binomial(round(A), f)                    makes
```

### Games

`n_slots` and `p_play` both come from `team_schedule`
([projection.py:145](../fantasy/analysis/projection.py)), fit **per NBA team**
from the pulled schedule rather than shared by the whole league. For each team,
every Monday–Sunday week of the season (including a bye week, counted as zero)
gives one observation of games played; `(n, p)` is chosen by matching a
Binomial's mean and variance to that team's real mean and variance, then
`p_play = p · status_factor · durability` folds in the individual player's
health and durability on top.

The point of fitting per team rather than assuming one shape for the league is
that real NBA schedules are not uniform: a team with a lot of clustered
back-to-backs has real variance well above what a flat `Binomial(4, 3.5/4)`
implies (some teams in the 2026-27 schedule fit to `n=5, p=0.64`, which allows
an occasional 5-game week; most fit closer to `n=4, p=0.80`), while the
league-wide mean itself is usually a little under the old 3.5 assumption
(3.2 for the 2026-27 slate). Both matter for the volume categories: the
low-variance old assumption understated how often a lineup gets an unusually
big or unusually thin week.

`team_schedule` falls back to `(SCHEDULE_SLOTS=4, GAMES_PER_WEEK/4)` for a
team it has no data for — no schedule pulled yet, or an explicit `--games`
override, which replaces every team's fit with one flat rate for a deliberate
what-if.

One caveat worth keeping in mind: the fit uses the season as a whole, not the
specific calendar dates of "this" fantasy week, because the snapshot carries
no fantasy-week date ranges to match against (see
[Limitations](#limitations)). It answers "how many games does this team play
in a typical week," not "how many games do they play in the week starting
next Monday."

### Usage

One draw per player per week, **shared across all of that player's
categories**. This is the only source of cross-category correlation in the
model, and it is the important one: minutes drive points, rebounds and assists
together, so a quiet week should be quiet everywhere rather than independently
average in nine places.

```
    usage_cv = sqrt( 0.12² + 1/n_eff )
```

The 0.12 is genuine week-to-week role drift; the `1/n_eff` term is the standard
error of the rate estimate itself. Adding them in quadrature is what makes a
thin sample project less confidently:

| `n_eff` | 5 | 10 | 20 | 40 | 70 | 82 |
|---|---|---|---|---|---|---|
| `usage_cv` | 0.463 | 0.338 | 0.254 | 0.198 | 0.169 | 0.163 |

A nine-game flier is not treated as though his rate were known.

### Counting stats

Drawn from a Gamma matched by moments to the mean and variance implied by the
realised `G` and `U`. `simulate._gamma` inverts the parameterisation:

```
    shape = mean² / var        scale = var / mean
```

Gamma is chosen over a normal because these are non-negative and right-skewed,
and over a negative binomial because it composes: the sum over a week is drawn
directly, with no loop over games.

The per-game variance is a **Poisson floor plus a proportional term**:

```
    v = mean + (cv · mean)²
```

The first term dominates for rare events, the second for volume. One `cv` per
category (`SPREAD`, [projection.py:33](../fantasy/analysis/projection.py))
covers the whole range of production:

| | cv | sd at 1.0 | at 2.5 | at 10 | at 20 |
|---|---|---|---|---|---|
| PTS | 0.35 | 1.06 | 1.81 | 4.72 | **8.31** |
| REB | 0.32 | 1.05 | 1.77 | **4.50** | 7.81 |
| AST | 0.38 | 1.07 | 1.84 | **4.94** | 8.82 |
| ST | 0.50 | **1.12** | 2.02 | 5.92 | 10.95 |
| BLK | 0.50 | **1.12** | 2.02 | 5.92 | 10.95 |
| 3PM | 0.45 | 1.10 | **1.94** | 5.50 | 10.05 |
| TO | 0.40 | 1.08 | **1.87** | 5.10 | 9.17 |

Bolded cells are the calibration targets — a 20 ppg scorer at sd ≈ 8, a 10 rpg
rebounder at ≈ 4.5, a 1.0 bpg blocker at ≈ 1.1 — all within about 5% of real
NBA game-to-game spreads.

Note that the **mean** uses `G·U` but the **variance** uses `G` alone. That is
deliberate, and it makes the decomposition below meaningful: `U` carries
uncertainty about the player's true level, `v` carries sampling noise around it,
and the marginal variance is the sum of the two.

### Percentages

FG% and FT% are never drawn as percentages. Attempts are drawn like any other
counting stat (with a tighter `ATTEMPT_CV = 0.22` — shot volume is steadier than
what comes of it), then makes are drawn as a binomial on those attempts.

The shooting rate `f` is itself drawn per player per week from a Beta with
`SHOOTING_ESS = 400` pseudo-shots, which is what makes a player run hot or cold
for a week instead of converting at exactly his season rate. Team percentages
are then **pooled over real makes and attempts**, never averaged across players
— the way Yahoo actually scores them, and the reason a high-volume
inefficient guard hurts more than a low-volume one.

### Where the uncertainty comes from

Disabling each source in turn, holding the mean fixed, on a real 14-man roster
(80,000 weeks):

| cat | weekly mean | sd | cv | schedule | usage | per-game | shooting |
|---|---|---|---|---|---|---|---|
| PTS | 632.0 | 75.3 | 0.119 | **49%** | 20% | 34% | – |
| REB | 218.0 | 29.8 | 0.137 | **44%** | 18% | 40% | – |
| AST | 135.9 | 20.0 | 0.147 | 32% | 15% | **55%** | – |
| ST | 42.0 | 8.4 | 0.200 | 16% | 7% | **77%** | – |
| BLK | 26.8 | 6.9 | 0.257 | 21% | 8% | **73%** | – |
| 3PM | 67.5 | 12.7 | 0.189 | 26% | 10% | **63%** | – |
| TO | 76.6 | 12.6 | 0.164 | 26% | 10% | **64%** | – |
| FG% | 0.475 | 0.025 | 0.052 | 5% | 1% | 2% | **93%** |
| FT% | 0.771 | 0.040 | 0.052 | 6% | 2% | 8% | **87%** |

(Shares do not sum to 100% — removing one source changes the interaction terms.
**This table predates the real-schedule change above** — it was measured under
the old flat `Binomial(4, 3.5/4)` assumption, and the real per-team fit has
both a lower mean and, for some teams, a wider spread, so the schedule share
here is likely a slight underestimate. It has not been re-measured; treat the
column as directionally right, not exact.)

Three things worth knowing from this:

- **Volume categories are decided by who plays.** Half the variance in weekly
  points is schedule and availability, not scoring. That is why the waiver
  search so often prefers a healthy mediocre player to an injured good one.
- **Rare categories are decided by noise.** Steals and blocks are 73–77%
  per-game randomness; no projection improvement will make them predictable.
- **The percentage categories rest almost entirely on `SHOOTING_ESS`.** 87–93%
  of their variance comes from that one hand-set constant. It currently puts
  team weekly FG% sd at 0.025, which matches real leagues, but it is the single
  most load-bearing number in the model and the first one to revisit.

---

## 4. Matchup scoring

`simulate.team_week`, `category_probs`, `matchup_summary`
([simulate.py:103](../fantasy/analysis/simulate.py))

A lineup is every rostered player **not parked on IL**. Its weekly total per
category is the column-wise sum over its players; percentages are pooled as
described above.

A category is won on a straight elementwise comparison across simulations, with
the inverted category (turnovers, in a standard league) flipped. Which
categories are compared, and which of them invert, comes from stage 0 — every
comparison function takes the league's category list explicitly rather than
assuming the standard nine:

```
    p_win(category) = mean( a > b )        or mean( a < b ) for TO
```

Ties are counted separately rather than split, so `p_win + p_tie + p_loss = 1`
exactly. Because the draws are continuous, exact ties are vanishingly rare
outside the degenerate case of a team against itself — but the accounting stays
honest rather than quietly awarding half a category.

The matchup itself is the majority across whatever the league scores:

```
    won  = Σ over categories of  1[a beats b]
    lost = Σ over categories of  1[b beats a]
    p_matchup_win = mean( won > lost )
```

`head_to_head` reports both layers plus the full distribution of the
category score, which is more informative than the mean: 3.8 expected
categories can be a stable 4-5 every week or a coin flip between 2 and 7.

`versus_field` runs the same simulated week against all eleven opponents and
averages. That distinction matters — a category you lose to everyone is a roster
construction problem, and one you lose only to the top two is not.

---

## 5. Waiver search

`waiver.add_drop` ([waiver.py:98](../fantasy/analysis/waiver.py))

### Objective

**Expected categories won per week**, averaged over the opponent set — one team
with `--vs`, otherwise all eleven. Change in win probability is reported
alongside but not optimised, because it is coarser — it registers a swap only
insofar as that swap flips whole matchups, so it discriminates poorly between
moves that are both genuinely good.

`Scorer` ([waiver.py:68](../fantasy/analysis/waiver.py)) stacks the opponents
into `(n_opponents × sims)` arrays so a candidate lineup is compared against the
whole field by broadcasting — 18 array operations per evaluation regardless of
how many opponents there are.

### The swap identity

This is what makes the search affordable. Because every player was drawn once
into a column, and a lineup total is a sum of columns:

```
    total(roster − drop + add) = total(roster) − column[drop] + column[add]
```

So evaluating a swap is one vector subtract and one add, not a fresh
simulation. Percentages are then recomputed from the adjusted makes and attempts
(`simulate.swap`, [simulate.py:119](../fantasy/analysis/simulate.py)) — which is
also why makes and attempts are carried through as separate columns rather than
collapsed into a ratio at draw time.

The second benefit is statistical. Every candidate is scored against the
**same** simulated weeks — common random numbers — so the difference between two
candidates has no sampling noise of its own, only the effect being measured.
At the default 4,000 simulations the top move reproduces to ±0.01 categories
across seeds, where independently simulating each candidate would need far more
draws for the same resolution.

### Search

1. **Score the baseline** roster against the opponent set.
2. **Price every roster spot** by what the team loses without it:
   `cost(p) = base − score(roster − p)`. This is a shortlisting heuristic, and
   it is measured against a short roster rather than a replacement — good enough
   to rank your own players, which is all it is used for.
3. **Take the `max_drops` cheapest** (default 6) as drop candidates.
4. **Filter free agents**: at least `min_gp` games (default 5) and `p_play > 0`,
   which removes small-sample noise and players who are ruled out.
5. **For every (add, drop) pair**, check lineup legality, apply the swap
   identity, and score.
6. **Rank by change in expected categories won.** `best_by_player` additionally
   collapses to one row per free agent, keeping their best drop.

### Lineup legality

`fills_lineup` ([waiver.py:39](../fantasy/analysis/waiver.py))

A recommendation that leaves you unable to field a legal lineup is worthless, so
each candidate roster is checked with **Kuhn's algorithm for maximum bipartite
matching**: slots on one side, players on the other, an edge where the player is
eligible for the slot. The swap survives only if every active slot can be filled
simultaneously.

Slots come from `v_roster_positions` with bench and IL removed, expanded to one
entry per slot. `Util` accepts anyone; `G` accepts PG/SG and `F` accepts SF/PF
(`FLEX`, [waiver.py:19](../fantasy/analysis/waiver.py)); everything else accepts
its own position.

Greedy assignment is not enough here, which is the whole reason for the
matching. Take a `PF` slot, a `C` slot, a pure centre and a `C/PF`: greedy hands
the centre slot to the `C/PF`, and the pure centre is then stranded with only
`PF` left — even though the legal assignment (`C/PF` to `PF`, centre to `C`)
exists. Kuhn's augmenting paths back that first choice out. With three
Util slots and two flex spots the constraint rarely binds — but it is what stops
the search recommending you drop your only centre.

---

## Cost

Memory is 11 arrays (seven counting categories, plus makes and attempts for two
percentages) of `sims × players` float32:

```
    11 × 10,000 × 199 × 4 bytes ≈ 88 MB
```

Measured on a 12-team league, 199 projected players, on a laptop:

| Command | Simulations | Time |
|---|---|---|
| `fantasy matchup <team>` | 10,000 | 1.3 s |
| `fantasy matchup` (11 opponents) | 10,000 | 1.4 s |
| `fantasy waivers` (96 legal swaps) | 4,000 | 0.9 s |

The draw dominates; the searches on top of it are nearly free. Raising `--sims`
is the cheap way to tighten a close call.

---

## Limitations

Roughly in order of how much they cost:

1. **The real schedule is not matched to the specific fantasy week.** The
   snapshot carries no fantasy-week date ranges, so `team_schedule` fits each
   team's games-per-week to its *whole season*, not to the actual dates of the
   week being analysed. A real bye week or a real Cup-heavy week is smoothed
   into the season average rather than reflected exactly.
2. **No game logs, so variance is modelled rather than measured.** `SPREAD` is
   one constant per category applied to every player; in reality a
   high-usage creator's points are steadier than a catch-and-shoot specialist's.
3. **`SHOOTING_ESS` carries the percentage categories** almost single-handedly
   (see the decomposition above).
4. **Players are independent.** Two players on the same NBA team, or on either
   side of the same real game, are drawn independently — including their game
   count: `team_schedule` gives teammates the same `(n, p)` shape, but each
   draws from it separately, so the model does not know they play the exact
   same games. This understates the variance of a stacked roster.
5. **Daily lineups are assumed, and assumed to be played perfectly.** Every
   non-IL player accrues every game they play — the daily-league assumption,
   surfaced by `rules.py` on every run because the snapshot cannot confirm it.
   A weekly-locked league would count only its 11 starters and is not
   supported. Even within a daily league this models the *ceiling*: the 11-slot
   cap binds on about 0.65% of nights (~0.1% of production, so negligible), but
   assuming perfect streaming favours deep rosters over top-heavy ones relative
   to what a real manager achieves.
6. **The drop-pricing pass measures a short roster**, not a replacement-level
   fill. It is a shortlist, not a valuation.
7. **No FAAB, waiver priority, or trade logic.** A recommended add is assumed
   to be obtainable.
8. **Only the latest pull is read, and only the current season.** The `v_*`
   views resolve to the newest snapshot; accumulated history is not used to
   estimate anything. `fantasy history pull` now stores four seasons of NBA
   totals per player in `nba_player_seasons`, but **nothing in `analysis/`
   reads it** — every rate, variance and availability figure below still comes
   from the single Yahoo snapshot. Prior seasons are context for a reader, not
   a model input; using them to shrink a small-sample rate toward a player's
   own career is an obvious next step and has not been done.

---

## Parameters

Everything tunable, in one place:

| Constant | Location | Effect |
|---|---|---|
| `PERIOD_WEIGHTS` | [projection.py:27](../fantasy/analysis/projection.py) | how hard recent form outvotes the season |
| `SPREAD` | [projection.py:33](../fantasy/analysis/projection.py) | per-game variance by category |
| `ATTEMPT_CV` | [projection.py:36](../fantasy/analysis/projection.py) | how much shot volume swings |
| `USAGE_CV` | [projection.py:41](../fantasy/analysis/projection.py) | baseline week-to-week role drift |
| `AVAILABILITY` | [projection.py:46](../fantasy/analysis/projection.py) | play probability by injury status |
| `GAMES_PER_WEEK` / `SCHEDULE_SLOTS` | [projection.py:49](../fantasy/analysis/projection.py) | fallback only — used when `team_schedule` has no data for a team, or `--games` overrides it |
| `SHOOTING_ESS` | [simulate.py:30](../fantasy/analysis/simulate.py) | how streaky shooting percentages are |
| `FLEX` | [waiver.py:19](../fantasy/analysis/waiver.py) | which positions a flex slot accepts |
| `SIMULATED` | [rules.py](../fantasy/analysis/rules.py) | Yahoo stat ids the model can score |

Which categories a league scores, and which invert, are **not** parameters —
they are read from the snapshot by `rules.py`. `query.CATEGORIES` supplies only
display order and the `rate` flag, shared with the web interface.

`tests/test_analysis.py` pins the behaviour each of these affects, so a
recalibration that breaks an invariant shows up immediately.

---

## What would make this better

The [Limitations](#limitations) section says what is wrong; this one says what to
build, roughly in order of what it buys. Each item is tied to a measured number
from the [variance decomposition](#where-the-uncertainty-comes-from) rather than
a hunch about what might help.

| # | Change | Buys |
|---|---|---|
| ~~1~~ | ~~Pull the NBA schedule~~ — **done**, see [Games](#games) | 44–49% of the variance in the volume categories, plus streaming |
| 1 | Match the schedule to the actual fantasy week | turns "a typical week" into "this week" |
| 2 | Backtest against real weekly results | makes every other item on this list measurable |
| 3 | Per-date stat pulls → real game logs | replaces the whole modelled variance layer with measurement |
| 4 | Difference consecutive snapshots | the same, for free, with no new API surface |
| 5 | Model the daily lineup | the difference between a good manager and a good roster |
| 6 | Correlate players in the same game | honest variance for stacked rosters |
| 7 | Replacement-level drop pricing | a real valuation instead of a shortlist |
| 8 | Trades, punts, and a playoff horizon | new analyses on the engine that already exists |

### 1. Match the schedule to the actual fantasy week

The schedule is pulled and used (`team_schedule`,
[projection.py:145](../fantasy/analysis/projection.py)) — `p_play` and the
games-played draw are now fit **per NBA team** from the real 2026-27 slate
instead of a league-wide 3.5 assumption. What is still missing is the fantasy
week itself: the snapshot has no table of week-number → date-range, so the fit
is against the *whole season's* weeks rather than the specific week being
analysed. A team on a bye or in a Cup-heavy stretch this week looks the same
as any other week.

Yahoo exposes this at `/league/{key}/settings` (`game_weeks`, not currently
pulled) or can be derived from `/league/{key}/scoreboard;week=N`. Once the
current week's actual date range is known, `team_schedule` can filter to that
one week's real game count per team instead of fitting a distribution over the
season — turning "a typical week" into "this week," which matters most right
before a bye week or a nationally-televised Cup stretch.

### 2. Backtest against real weekly results

Nothing currently checks whether a "34% to win" week actually comes in near 34%.
Every number in this document is internally consistent and externally
unvalidated, and until that changes, improvements to the model are unfalsifiable
— including the ones on this list.

`/league/{key}/scoreboard;week=N` returns each completed matchup with its
per-category totals and category-by-category result. That is a labelled test
set: for every past week, what the model would have predicted against what
happened.

What to build:

- a `matchups` table (week, both teams, per-category totals, per-category result);
- a replay path that projects a past week from the snapshot preceding it;
- **Brier score** per category and a **reliability curve** — bucket predictions
  by decile and check that the 30% bucket wins about 30% of the time.

The most likely finding is that the model is *overconfident* — that is the
default failure of any simulation with independent players (item 6) and a fixed
game count (item 1). Reliability curves would show it immediately.

Do this second, not last. It converts the rest of the list from taste into
engineering.

### 3. Per-date stat pulls → real game logs

`SPREAD` is currently one constant per category applied to every player, which
is the crudest part of the model. Real game logs would replace the whole layer
with measurement: per-player variance, and the fact that a high-usage creator's
scoring is genuinely steadier than a catch-and-shoot specialist's.

Yahoo's player stats endpoint takes a `type` parameter, which `client.py`
already maps for the four rolling windows. Daily-scoring sports also accept
`type=date;date=YYYY-MM-DD` — **verify this against the live API before
building on it**, but if it holds, a season of game logs is a loop over dates
through the existing `player_stats` path and a new `stat_period` value. The long
`player_stats` schema already accommodates it without migration.

That would also let `SHOOTING_ESS` be fitted rather than hand-set — worth doing
early, since it alone accounts for 87–93% of the variance in the percentage
categories.

### 4. Difference consecutive snapshots

The cheaper half of item 3, available with **no new API surface at all**. The
store is append-only by design: every pull stamps a full set of season totals.
Subtracting consecutive pulls' season totals gives actual production between
them, and subtracting `GP` gives the games it came in.

Pull weekly and you accumulate real weekly observations per player — enough to
fit `USAGE_CV` and validate `SPREAD` at the aggregate level, even without
game-level detail. This costs nothing but time and a `v_player_deltas` view over
`player_stats`.

It is worth wiring up now precisely *because* it is retroactive: the data starts
accruing from the first extra pull, so the sooner it runs, the sooner items 2
and 3 have something to chew on.

### 5. Model the daily lineup

Every non-IL player currently accrues every game they play. With 11 active slots
and ~14 healthy players the cap rarely binds, so this is a smaller error than it
looks — but it means the model cannot reward day-to-day management or punish
neglect, and it slightly overstates deep rosters.

With the schedule in hand (item 1) this becomes a per-day assignment: for each
date, match available players to the 11 slots — the same bipartite matching
`fills_lineup` already implements, run per day and maximised by projected value
rather than just checked for feasibility.

### 6. Correlate players in the same game

Players are drawn independently. Two players on the same NBA team, or on
opposite sides of the same game, are not — pace, blowouts, and overtime move
everyone on the floor together. Independence understates the variance of a
stacked roster and therefore *overstates* how reliably it wins categories.

The fix composes with what is already there: the usage factor `U` is per player,
so adding a shared per-game factor drawn once per (date, game) and multiplied
into every participating player's exposure is a small change to `draw` — but it
needs the schedule (item 1) to know who shares a game.

### 7. Replacement-level drop pricing

`add_drop` prices a roster spot as `base − score(roster − p)`, which measures
against a *short* roster rather than against what would replace him. It is
honest about being a shortlisting heuristic, and it is fine for that, but it is
not a valuation: it systematically overvalues everyone, since playing 13 is
worse than playing 14 of anyone.

Pricing against the best available free agent instead turns `cost` into true
replacement value, which is the number worth showing in the standalone "who is
droppable" table.

### 8. New analyses on the existing engine

The swap identity generalises, so several of these are small:

- **Trades.** A two-sided swap is the same column arithmetic applied to both
  rosters at once. `simulate.swap` currently moves one player each way, so it
  needs widening to take column *sets*; the scoring above it is unchanged.
- **Punt builds.** Expected categories won treats all nine equally, which is
  exactly wrong for a punt strategy. A build that concedes FT% and TO wants to
  maximise `P(win ≥ 5)`, which is one sum away from the score distribution
  `matchup_summary` already returns. Making the objective selectable is a few
  lines in `Scorer`.
- **Playoff horizon.** Everything here is one week. `v_league_settings` already
  stores `playoff_start_week`, so the same machinery could evaluate a move
  against the weeks that decide the season rather than the next one.
- **FAAB and waiver priority.** A recommended add is currently assumed
  obtainable. `uses_faab` is already in the settings table; the missing piece is
  a cost model, so gains can be expressed per dollar rather than absolutely.

### Operational note

`fantasy waivers` is only as good as the pool it can see. A snapshot pulled with
`--fa-limit` leaves the search a fraction of the real free agents — the current
one has 25, of which 16 clear the games filter. Run `fantasy pull` with no
`--fa-limit` before trusting a waiver ranking.
