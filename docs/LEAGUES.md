# Leagues

What each league I play in actually does, written down by hand.

The model assumes most of its rules. `fantasy rules` prints them split by source,
and the `assumed` rows are assumed because Yahoo never returned them — not because
they are unimportant. Two of them (`lineups`, `acquisition limits`) have no column
in the schema at all, `league_settings` is a nearly-empty row that a re-pull cannot
fix while Yahoo 403s, and `analysis/rules.py` never reads that table anyway. So
this file is the only place a league's real settings exist.

It is also the only place a league *other than* `466.l.28641` exists. That one
league is the whole database; for anything else here, this block is all there is.

## How to read this file

**`?` means unknown, not default.** A blank field has not been filled in yet. If
an answer depends on a `?`, say so — "the league's waiver type isn't recorded, so
I've assumed an add is free" — rather than quietly reaching for the Yahoo default.
Getting a `?` filled in is usually a two-minute look at the league page and is
worth asking for.

**Precedence.** The snapshot wins for anything Yahoo actually returned: categories,
roster slots, teams, rosters, stats. This file wins for every `assumed` row in
`fantasy rules`. Where the two disagree, report the disagreement instead of
quietly picking a side.

**Nothing parses this file.** The blocks are TOML-shaped because that reads
cleanly, not because anything loads them. Editing this changes no behaviour; it
changes what an agent *says* about the behaviour. If a setting here contradicts
the model, the model still ran the old way — flag it, don't pretend otherwise.

**One database, one league.** Only `466.l.28641` has been pulled, and pulling a
second league into the same file would not help: `rules.py`, `query.py` and
`report.py` all read the league with an unfiltered `limit 1`, so a second league
would be picked arbitrarily and every downstream number would silently belong to
whichever one came back first. A second league needs its own database file via
`FANTASY_DB`. Until then, treat non-snapshot leagues here as reference only — no
`fantasy` command can be run against them.

See `CLAUDE.md` for the four ways the snapshot itself will mislead you. Those are
data caveats; these are rules caveats.

## What to fill in first

In rough order of how much each one moves an answer:

1. **`lineup_lock`** — daily or weekly. The model assumes daily and perfect
   management, which is the ceiling of a streaming strategy. A weekly-locked
   league counts only its starters, so every counting-category projection is too
   high, and `fantasy waivers` is measuring a lever that doesn't exist.
2. **`max_adds_week` / `waiver_type` / `faab_budget`** — the model treats an add
   as free and unlimited. A cap or a budget turns the waiver board from a ranking
   into a spending decision.
3. **`format` and `keepers`** — decides whether a move is judged on this season
   or on future value. Nothing in the store knows the difference.
4. **`playoff_teams` and `regular_weeks`** — decides whether a team is playing for
   seeding or already out.
5. Everything else.

## Template

Copy this block for a new league. Leave `?` where you don't know rather than
guessing — a `?` is information and a wrong value isn't.

```toml
[league."<key or platform id>"]

# --- Identity ---
name            = "?"
platform        = "?"          # Yahoo | ESPN | Fantrax | Sleeper
season          = "?"
teams           = "?"
format          = "?"          # dynasty | keeper | redraft
keepers         = "?"          # how many carry over, at what cost
founded         = "?"          # first season
horizon         = "?"          # how long the league is expected to run
my_team         = "?"
stakes          = "?"          # money, trophy, nothing
in_snapshot     = false        # true only for a league `fantasy pull` has stored

# --- Scoring ---
scoring         = "?"          # h2h category | h2h points | h2h most-cats | roto
categories      = ["?"]
inverted        = ["?"]        # categories where lower wins
matchup_length  = "?"          # weeks per matchup
tiebreaker      = "?"

# --- Roster and lineups ---
active_slots    = "?"
bench           = "?"
il              = "?"
lineup_lock     = "?"          # daily | weekly
position_elig   = "?"          # games needed to gain a position, if any
max_games_week  = "?"          # per-position games cap, if any

# --- Transactions ---
waiver_type     = "?"          # rolling list | FAAB | none
faab_budget     = "?"
waiver_period   = "?"
max_adds_week   = "?"
max_adds_season = "?"
trade_deadline  = "?"
trade_review    = "?"          # commissioner | league vote | none
pick_trading    = "?"

# --- Draft ---
draft_type      = "?"          # snake | linear | auction
draft_pool      = "?"          # who returns to the pool each year
draft_order     = "?"          # how the order is set
keeper_cost     = "?"          # what a kept player costs

# --- Season shape ---
regular_weeks      = "?"
playoff_start_week = "?"
playoff_teams      = "?"
seeding            = "?"
consolation        = "?"
```

**House rules and norms** — prose. What a new manager would be told out loud and
never see written down: who trades, who is rebuilding, how veto votes really work,
tolerance for tanking or for streaming a roster spot every day.

**What this changes for the model** — one line per `assumed` row in
`fantasy rules` that this league contradicts, naming the label verbatim and saying
what to do about it.

---

## Lean Green Money-Makin Machine — `466.l.28641`

The league in the snapshot. Identity, Scoring and the roster slots are read from
`pull_id=1`; the transaction, lineup and keeper rules were supplied by hand, since
Yahoo never returned them. What is still `?` is genuinely not known.

```toml
[league."466.l.28641"]

# --- Identity ---
name            = "Lean Green Money-Makin Machine"
platform        = "Yahoo"
season          = 2025
teams           = 12                    # v_leagues.num_teams
format          = "dynasty"             # but see the keeper note below — only 3
keepers         = 3                     # MAX 3 players carried to next season
founded         = 2024                  # 2 seasons played going into 2026-27
horizon         = "5+ more years"
my_team         = "466.l.28641.t.9"     # "Red Eyes Black Dragon", manager Jason
stakes          = "?"
in_snapshot     = true                  # pull_id=1, taken 2026-09-02, season over

# --- Scoring ---
scoring         = "h2h category"        # v_leagues.scoring_type = "head"
categories      = ["FG% (5)", "FT% (8)", "3PTM (10)", "PTS (12)", "REB (15)",
                   "AST (16)", "ST (17)", "BLK (18)", "TO (19)"]
inverted        = ["TO"]                # ASSUMED — every sort_order is NULL
matchup_length  = "1 week"
tiebreaker      = "?"

# --- Roster and lineups ---
active_slots    = "PG, SG, G, SF, PF, F, C, C, Util, Util, Util"   # 11
bench           = 3
il              = 2
lineup_lock     = "daily"               # matches what the model assumes
position_elig   = "?"
max_games_week  = "none"                # no per-week or per-season games cap

# --- Transactions ---
waiver_type     = "none"                # no waiver list; a drop is immediately
                                        # free to anyone, first come first served
faab_budget     = "n/a"
waiver_period   = "none"                # no waiting period at all
max_adds_week   = 4                     # the model assumes unlimited
max_adds_season = "none"                # no season cap, only the weekly 4
trade_deadline  = "?"
trade_review    = "?"
pick_trading    = "yes"                 # players tradeable for future picks

# --- Draft ---
draft_type      = "?"                   # snake or linear not recorded
draft_pool      = "every player not kept"
draft_order     = "3-tier lottery"      # see below
keeper_cost     = "none"                # keepers cost no pick — they just occupy
                                        # the first 3 roster spots, so a team's
                                        # first pick is its 4th player

# --- Season shape ---
regular_weeks      = "?"                # current_week reached 23
playoff_start_week = 21                 # league_settings — the one field stored
playoff_teams      = "?"
seeding            = "?"
consolation        = "?"
```

`league_settings` holds exactly one usable value. `playoff_start_week = 21` is
stored; `max_teams`, `num_playoff_teams`, `waiver_type`, `trade_end_date`,
`draft_type`, `uses_playoff` and `uses_faab` are all NULL, because that row
predates the current parser (which writes `0`/`False`, never NULL, for a missing
field). It is stale data, not a live bug, and Yahoo's 403 means a re-pull cannot
refill it. `fantasy report` already raises this as the `settings_incomplete`
finding. Every one of those seven is answered by hand above instead.

### House rules and norms

**Dynasty in name, keeper-3 in mechanics.** The league runs as a dynasty and is
expected to last 5+ more years, but only **3** players carry to the next season —
so roughly 11 of the 14 roster spots reset every year. That is a much shorter
carryover than the word "dynasty" usually implies, and it is the single most
important thing to hold in mind when reading a dynasty ranking against this
roster.

**The waiver wire is a race.** There is no waiver period and no FAAB: a dropped
player is available to all 12 teams the instant he is dropped. Nobody can queue a
claim, so being first matters more than being right, and a genuinely good drop
will not survive long enough to be deliberated over.

**The draft resets almost everything.** Every player not kept goes back into the
pool, so each team drafts 11 of its 14 roster spots from scratch. Keepers cost no
pick; they simply fill the first three slots, which is why a team's first pick is
its fourth player.

**Draft order is a three-tier lottery**, drawn within each tier rather than
ordered by record:

| Tier | Teams | Picks drawn for |
|---|---|---|
| Bottom | last 4 finishers | 1–4 |
| Middle | the other 6 | 5–10 |
| Top | first 2 finishers | 11–12 |

Two things follow. Finishing **3rd through 8th is all the same** for draft
purposes — there is no ordering within the middle tier, so once a season is out
of reach the only thing left to play for is dropping into the bottom four.
Finishing **1st or 2nd costs real draft capital**, which is the league's brake on
a good team compounding.

*Still unrecorded:* how active the league is in trades, who is rebuilding, and how
the commissioner handles vetoes.

### What this changes for the model

Every `assumed` row in `fantasy rules` for this league, and what is known about it:

| `fantasy rules` label | model assumes | truth | what to do |
|---|---|---|---|
| `lineups` | daily | **daily — confirmed** | The assumption is correct here. Combined with no games cap, a player accrues every game he plays, so the model is counting the right thing. |
| `lineup management` | perfect | still assumed | A ceiling, not a forecast. Daily lineups make that ceiling reachable in principle, but it still assumes you never miss a slot. Quote model numbers as an upper bound. |
| `acquisition limits` | none | **4 adds/week** | The search treats an add as free, so it will happily recommend more churn than the league allows. Take the top of its ordering, not its whole list, and stop at four. |
| `inverted category` | TO only | almost certainly right | Standard 9-cat. Low risk, but it is inferred from `LOWER_WINS`, not read. |
| `games per team` | 3.20/wk, fit to the NBA schedule | n/a | Read from `nba.com`, not assumed — but fit against the whole season, so a real bye week looks like any other week. |

Four more things the model has no representation of at all:

- **Keepers.** Only 3 players carry over, but `rankings composite build` folds
  together sources that are all `dynasty` — they rank assets on a full-carryover
  horizon. A 19-year-old's composite rank therefore overstates his worth here
  unless he is one of your three keepers or a trade chip. Say which of the two you
  mean when quoting `rankings composite show --team me`.
- **Draft picks.** Players are tradeable for future picks and nothing in the store
  knows a pick exists. Any trade involving one is outside the model entirely — the
  composite ranking holds picks out of the rerank, and no simulation prices them.
  The tiered lottery makes a pick's worth lumpy rather than linear: a bottom-tier
  slot is a draw at 1–4, a middle-tier slot is a draw at 5–10, and the difference
  between them is far larger than the difference within either.
- **Where you finish.** The model maximises weekly win probability and has no
  notion of end-of-season position. Given the tiers, a team locked out of
  contention gains nothing from climbing to 5th and gains a top-4 draw from
  falling to the bottom four. `fantasy matchup` and `fantasy waivers` will never
  say that; they will always play for the current week.
- **Availability on the wire.** `fantasy waivers` ranks free agents by how much
  they move the odds, not by whether you can actually get them. With no waiver
  period that gap is real, and the free-agent pool in the snapshot is truncated to
  25 anyway.

Nothing here backtests. Report probabilities as "the model puts this at X%",
with the assumptions that produced them.

---

## <next league>

Copy the template above.
