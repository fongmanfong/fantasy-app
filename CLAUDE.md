# Working in this repo

`fantasy` is a CLI that snapshots a Yahoo Fantasy NBA league into DuckDB and runs
analysis over it. Two halves: a **pull** side (Yahoo → DuckDB, append-only) and a
**read** side (queries, a local web view, and a Monte Carlo model of a fantasy week).

Read [README.md](README.md) for what the commands do and
[docs/ALGORITHMS.md](docs/ALGORITHMS.md) for how the model works and what it
cannot do. This file is the part that is not obvious from the code.

## Before you do anything

**Use the venv.** `.venv/bin/python`, `.venv/bin/fantasy`. There is no global install.

**DuckDB takes an exclusive lock on the file.** Only one writer at a time. The
writers are `pull`, `rankings pull`, `schedule pull` and `history pull`; two of
them cannot run concurrently, and an open `duckdb` shell — or a running
`fantasy view` — blocks any of them. Everything else — `sql`, `tables`,
`status`, `rules`, `matchup`, `waivers`, `report`, `view`, `rankings show`,
`schedule show`, `history show` — opens the file read-only and *can* share it.
Do not fan analysis out across parallel shells expecting them to interleave —
run them in sequence.

**The Yahoo API currently 403s every Fantasy endpoint.** `pull`, `leagues` and
`auth status` will all fail with `403 Forbidden`. This is an account/app
permission problem on Yahoo's side, not a bug in the client, and it is
documented in the user's notes. Do not spend time debugging it or re-running
`auth login`. Work from the snapshot already in `data/fantasy.duckdb`.

## The snapshot you will actually be working with

One pull, `pull_id=1`, taken 2026-09-02, of league `466.l.28641`
("Lean Green Money-Makin Machine", 2025 season, 12 teams). The user's team is
`466.l.28641.t.9` ("Red Eyes Black Dragon"). 186 rostered players, 25 free agents.

Four things about it will mislead you if you do not know them:

1. **All four stat windows are identical.** The season was over when it was
   pulled, so Yahoo returned full-season figures for `last_7`, `last_14` and
   `last_30` alike. The recency blend in `projection.py` is real code but a
   no-op on this data. Do not "discover" that recency weighting has no effect
   and conclude it is broken. For any question about a player's trajectory, use
   `v_player_history` instead — four seasons off nba.com, pulled separately.
2. **The free-agent pool is truncated.** It was pulled with `--fa-limit`, so
   there are 25 free agents, of which 16 clear the model's games filter.
   `fantasy waivers` is therefore searching a fraction of the real pool. Say so
   when reporting waiver results.
3. **`league_settings` is nearly all NULL.** That row predates the current
   parser (which returns `0`/`False`, never NULL, for missing fields). It is
   stale data, not a live bug — see issue #4.
4. **Stat *names* in this snapshot are unreliable.** It predates a stat-map fix,
   so makes/attempts are transposed: `stat_id 10` is stored with
   `stat_name='3PTA'` when it is really 3PTM. **Key on `stat_id`, never
   `stat_name`.** `query._names()` handles the transposition for the read path
   and `rules.SIMULATED` maps by id; follow that convention in anything new.

## Driving the analysis

**If you are here to assess the team and recommend moves, start with
`fantasy report`.** It is the front door: one markdown document carrying the
roster, the category profile, the standings, the waiver board, the model's
assumptions, and a generated list of what to research externally. Read its
section 1 before quoting any number from it, and section 7 to decide what to go
look up — that section names the players where outside information actually
changes the answer, ranked by how little the model knows about them.

```sh
.venv/bin/fantasy report          # overwrites reports/summary.md
.venv/bin/fantasy report --out -  # to stdout instead
```

`reports/summary.md` is always the current report at a fixed, known path —
read it directly rather than guessing a filename. `reports/` is gitignored.

**Read [docs/LEAGUES.md](docs/LEAGUES.md) alongside it.** That is the hand-written
record of what each league actually does — the settings Yahoo never returned, which
is most of them. It outranks every `assumed` row in `fantasy rules`; the snapshot
still outranks it for anything Yahoo did return. A field written `?` there is
**unknown, not the default** — if an answer depends on one, say so rather than
quietly assuming. It is also the only place leagues other than `466.l.28641`
exist at all.

The rest of the CLI answers narrower questions:

```sh
.venv/bin/fantasy status                     # how stale each of the five sequences is
.venv/bin/fantasy rules                      # what the model reads vs assumes
.venv/bin/fantasy matchup "Guan Yu"          # per-category odds against one team
.venv/bin/fantasy matchup                    # against all 11 opponents
.venv/bin/fantasy waivers Starboy            # add/drops for one matchup
.venv/bin/fantasy sql "select * from v_my_team"
```

Teams resolve loosely — team key, team id (`8`), or part of a name or manager.

## The three outside sources

Besides the Yahoo league, the store pulls in three things on their own cadence.
Each has its own pull sequence and its own orchestrator, and none is stamped
with a league key, because none is specific to one league.

```sh
.venv/bin/fantasy rankings sources           # what this app knows how to scrape
.venv/bin/fantasy rankings pull hashtag_dynasty
.venv/bin/fantasy rankings show hashtag_dynasty
.venv/bin/fantasy rankings show hashtag_dynasty --notes   # its written commentary
.venv/bin/fantasy rankings composite build   # fold every source into one ordering
.venv/bin/fantasy rankings composite show --team me
.venv/bin/fantasy schedule pull              # season inferred from today's date
.venv/bin/fantasy schedule show --nba-team BOS
.venv/bin/fantasy history pull               # only the seasons not yet stored
.venv/bin/fantasy history show "Trae Young"
```

- **Rankings** (`sources/rankings/`) are a registry: each site is one module
  with a pure `parse(text)` next to `hashtagbasketball.py`, registered in the
  `SOURCES` dict. Adding a site changes nothing else in the app.
- **`angle_dynasty` has no permanent URL.** Angle publishes each edition of its
  Top 300 as a new WordPress post embedding a new Google Sheet, so that source
  is registered `remembers_url=True`: the URL of its last successful pull is the
  default for the next one, and `--url` only has to be given when a new edition
  appears. It accepts the post, the embedded `pubhtml` link, an `/edit` sheet
  URL or a CSV link alike — `angle.resolve` rewrites any of them to the sheet's
  CSV export, following the post's `<iframe>` when given an article. Every row
  carries the sheet's own title as `extra["edition"]`, so a stored ranking still
  says which edition it is once the URL behind it has moved on.
  ```sh
  .venv/bin/fantasy rankings pull angle_dynasty --url <new post or sheet>
  ```
- **One ranking out of several.** `rankings composite build` folds every source
  of the same registry `kind` (`Source.kind`, currently all `dynasty`) into one
  ordering and appends it as a `composite_runs` row plus its `composite_rankings`
  — derived rather than pulled, but on the same append-only footing, with the
  ranking pull ids and the parameters recorded so an old ordering is still
  legible after the pulls behind it have moved on. The method is in
  `analysis/composite.py` and the judgment calls are all about **absence**: a
  source that ranks 400 and leaves someone off has said something, a source that
  publishes 75 has not, and a slot that exists in a source's numbering with no
  row in it (dynatyze has 7) is a hole in the scrape rather than either. Read
  that module's docstring before changing the numbers — the decay curve barely
  moves the order, and those three rules move players tens of places.
- **Only one source writes prose.** hashtagbasketball puts a "Dynasty Outlook"
  next to some of its numbers, stored as `extra["outlook"]` and read with
  `rankings show --notes`. Angle and dynatyze publish none — checked against
  Angle's raw CSV and dynatyze's own `dynasty-rankings.md` endpoint, and written
  into both module docstrings so it is not re-investigated. `extra` is a JSON
  column and `db._insert` drops unknown keys, so enriching what a parser returns
  needs no migration.
- **The schedule** (`sources/schedule/`) is stats.nba.com via `nba_api`, and it
  is what `projection.team_schedule` fits per-team games-per-week from. Without
  it the model falls back to a flat 3.5 and says so in `fantasy rules`.
- **Player history** (`sources/history/`) is stats.nba.com's
  `LeagueDashPlayerStats`, season totals for everyone who appeared, one pull row
  per season. It exists because **the snapshot has one season and four identical
  stat windows** — nothing else in the store can say whether a player is
  climbing, declining or durable. One request per season, not per player: the
  endpoint returns ~570 rows at once. Totals are stored, not per-game figures;
  `v_player_history` divides by `gp` and restricts to players in the snapshot.
  Seasons resolve independently, so one throttled season does not cost the rest.
  **A stored season is skipped** — `history.should_pull` — because a finished
  season's totals are final; the two exceptions are the season in progress,
  whose totals are still accumulating, and `--refresh`. Reach for `--refresh`
  after a fresh `fantasy pull`: `player_key` is resolved at insert time, so
  seasons stored against an older snapshot keep the matches they made then.
  **Nothing in `analysis/` reads it yet** — `projection.py` still builds off the
  Yahoo snapshot alone, so this is context for a human or an agent, not a model
  input.

**Names are the join.** An outside source prints "Nikola Jokic" where Yahoo has
"Nikola Jokić", so both sides go through `names.normalize()` — case, accents,
punctuation, suffixes, and a short first-name nickname table, deliberately
never the surname. A ranking row that still doesn't match is **stored with a
null `player_key` rather than dropped**: an unmatched name is a signal about
`normalize()`, and throwing it away would hide the miss. `fantasy rankings show`
prints those as `unmatched`.

Every outside source resolves a name through the same map —
`query.player_keys_by_name(con)`. Use it rather than writing the join again.

The same normalisation exists twice — once in `names.py` and once as the
`name_key()` SQL macro in `schema.sql`, used by the `player_name_key` column.
**If you change one, change the other.** Nothing currently tests that they
agree — and they do *not* agree on first-name nicknames: `names.normalize()`
folds `Anthony`→`tony`, `Cameron`→`cam`; the `name_key()` SQL macro does not.
`composite_rankings.player_name_key` is written by the Python path, so anything
joining to it (`fantasy/redraft.py` does) must key on `names.normalize()`, not
the macro, or it silently drops Edwards / Curry / Boozer.

## The Yahoo redraft board

`fantasy/redraft.py` holds a hand-pasted copy of Yahoo's draft-analysis page
(the login-walled, client-rendered one) as the `BOARD` constant.
`fantasy rankings redraft load` (or `python -m fantasy.redraft`) writes it into
the `redraft_ranks` table and rebuilds the `v_redraft_vs_dynasty` view, which
full-outer-joins it to `v_composite_rankings`. It sits under `rankings` because
it *is* a ranking — Yahoo's redraft one — read against the composite; it is
**not an outside source**, though: no pull sequence, no league key, not
append-only, not in `schema.sql`, so a fresh database has no board until the
command runs and `query.keeper_board` raises with the reload command when the
view is absent. `redraft_rank` is Yahoo's Rank column (projected value);
`avg_pick` is ADP, kept alongside because the two diverge where the market
prices in risk (a torn Achilles) the projection ignores.

```sh
.venv/bin/fantasy rankings redraft load                  # after editing BOARD
.venv/bin/fantasy rankings redraft show --team me
.venv/bin/fantasy rankings redraft show --gap 20         # buy-lows and sell-highs
.venv/bin/fantasy rankings redraft show --trios          # the keeper-trio ranking
```

`fantasy view` also serves it as the **Keepers** tab (`/api/keepers` →
`query.keeper_board`): the scatter, the same board, and each team's top-3
keeper trio. Both read the view live, so a fresh `rankings composite build`
moves the blended numbers without touching the board.

For anything the CLI does not already print, **call the Python API rather than
parsing terminal output**. Every entry point takes an open connection and
returns plain dicts:

```python
from fantasy.store import db
from fantasy.analysis import composite, matchup, projection, rules, waiver

with db.connect(read_only=True) as con:
    rules.load(con)                                   # refuses leagues it can't model
    matchup.head_to_head(con, team_b="Guan Yu", sims=20000)
    matchup.versus_field(con)
    waiver.add_drop(con, opponent="Starboy", sims=8000)
    projection.build(con)                             # per-player rates, before simulation
    composite.load(con)                               # the stored composite ranking
```

Past seasons have no analysis module of their own yet — read `v_player_history`
directly, one row per (player, season), already per game:

```sql
select season, gp, mpg, pts, reb, ast, tpm, stl, blk, tov, fg_pct, ft_pct
from v_player_history where full_name = 'Cade Cunningham' order by season;
```

`matchup.prepare(con, ...)` returns `(players, draws, rules)` if you want to
simulate once and run many comparisons against the same draws — that is the
cheap way to answer a batch of questions, and it gives common random numbers so
the differences between scenarios are noise-free.

### Reporting results honestly

This matters more than usual here, because the model emits confident-looking
probabilities that nothing has validated.

- **Always surface the assumptions.** Every run prints them; `fantasy rules`
  expands them. The load-bearing one is that lineups are daily and played
  perfectly. Do not quote a probability without them.
- **Nothing backtests these numbers.** There is no comparison against real
  weekly results anywhere in the repo. Say "the model puts this at 34%", not
  "you have a 34% chance".
- **Do not over-read steals and blocks.** They are ~75% per-game noise
  (see the variance decomposition in `docs/ALGORITHMS.md`). A 3-point edge
  there is not a finding.
- **Absolute probabilities move ~1pp between seeds at 10,000 sims; differences
  between candidates are far more stable** (±0.01 categories at 4,000), because
  candidates share draws. So trust "this add is better than that one" more than
  "this add is worth exactly +0.33". Check with `--seed`.

## Architecture, and the invariants worth preserving

```
fantasy/
├── cli.py            Typer commands; presentation. No model logic lives here.
├── config.py         paths and environment; DB_PATH, token location, credentials
├── names.py          normalize() — the join key between an outside name and v_players
├── query.py          read-side queries over the latest snapshot
├── report.py         `fantasy report`; build() composes data, render_markdown() emits prose
├── server.py         stdlib HTTP + JSON for `fantasy view`
├── templates/        app.html, the single page `fantasy view` serves
├── pull.py           league snapshot orchestration; a failed step is recorded, the rest continues
├── rankings.py       ranking-site pull orchestration
├── composite.py      composite-run orchestration; the only writer that reads first
├── schedule.py       NBA schedule pull orchestration
├── history.py        past-season NBA player stats pull orchestration
├── redraft.py        hand-pasted Yahoo redraft board + v_redraft_vs_dynasty; `fantasy rankings redraft load` reloads it
├── yahoo/            auth, client, parse (parsers pure, no I/O)
├── sources/          everything pulled in besides your Yahoo league
│   ├── rankings/     a registry of interchangeable scrapers behind one SOURCES dict
│   ├── schedule/     stats.nba.com, split client.py/parse.py the same way yahoo/ is
│   └── history/      stats.nba.com again, past-season player totals, same split
├── store/            db.py + schema.sql
└── analysis/
    ├── rules.py      league rules from the snapshot; runs first, refuses what it can't model
    ├── projection.py player -> per-game rates, variance, availability
    ├── simulate.py   Monte Carlo; one column per player
    ├── matchup.py    head-to-head and against-the-field
    ├── waiver.py     add/drop search + lineup legality
    └── composite.py  many ranking sources -> one ordering; build() and load()
```

`cli.py` is presentation, but it is not *only* rendering: a few commands build
their own display SQL (`schedule show`, `rankings show`), `report` owns writing
the file, and `auth status` makes a live call. The line that does
hold, and is worth keeping, is that **no model or simulation logic lives in the
CLI** — if you find yourself computing something there that a caller other than
the terminal would want, it belongs in `query.py` or `analysis/`.

- **The store is append-only.** Nothing is ever UPDATEd or DELETEd except a
  pull row's own status. There are now **four independent pull sequences** —
  `pulls` (the league), `ranking_pulls`, `nba_schedule_pulls`,
  `nba_season_pulls` — and each family of `v_*` views resolves to the newest
  successful pull *of its own kind*, so a stale schedule and a fresh league
  snapshot coexist happily. `nba_season_pulls` opens one row **per season**, so
  a four-season run is four pulls that succeed or fail on their own. Keep it that way;
  accumulated history is the basis for several planned improvements.
  `composite_runs` is **not** a fourth pull sequence — nothing there comes off
  the wire — but it is stamped and resolved the same way, and `composite build`
  appends a run rather than replacing one, so two orderings can be compared.
  **`fantasy status` is how you read all of that back** — `query.store_status`
  and its `SEQUENCES` table, one row per league, source and season, because
  three of the five open a row per subject and a single "last pulled" would hide
  a season that failed while its siblings succeeded. A new sequence belongs in
  `SEQUENCES`; nothing else has to change. Before quoting a number out of the
  store, check that what produced it is not months older than the rest.
- **The schema documents itself in the catalogue.** Every table, view and
  non-obvious column carries a `COMMENT`, applied by the block at the end of
  `schema.sql`. They are readable from a read-only connection, so
  `select table_name, column_name, comment from duckdb_columns()` is the
  fastest way to learn the store from a `duckdb` shell without opening this
  file. Two things to know: **the comment block must stay last**, because
  `CREATE OR REPLACE VIEW` drops the comments on the view it replaces; and
  comments only land when `init_schema` runs, which is inside the three pull
  commands — an existing database picks up new ones on its next pull, or
  from `db.init_schema` on a writable connection.
- **Parsers are pure.** `yahoo/parse.py` takes Yahoo-shaped dicts and returns
  flat rows, no network. That is why it is testable.
- **Analysis returns plain dicts.** The CLI, the JSON server and a REPL all use
  the same calls. Do not put formatting in the analysis modules.
- **Nothing about the league is hardcoded.** Categories, the inverted category
  and roster slots come from the snapshot via `rules.py`. If you add a scored
  quantity, add it to `rules.SIMULATED` (keyed by Yahoo stat id) or the run will
  correctly refuse. Which side of a category *wins* is decided in exactly one
  place — `query.beats(a, b, cat)`, which works on scalars and numpy arrays
  alike — so never write `if cat["neg"]` at a comparison site. Bench and IL
  slots go through `rules.is_bench` for the same reason.
- **Simulate once, reuse the columns.** `simulate.draw` gives a
  `(sims × players)` array per category; a lineup is a set of columns to sum and
  a swap is `− column[drop] + column[add]`. If you find yourself re-simulating
  to evaluate a variant, you are doing it the slow and noisy way.

## Conventions

- **Dependencies are deliberately few** — duckdb, numpy, requests,
  requests-oauthlib, nba_api, typer, rich, python-dotenv. The web layer is
  stdlib on purpose. Do not add scipy/flask/pandas without asking.
  **`nba_api` does pull pandas in transitively**, which is why
  `sources/schedule/client.py` imports it *inside* `fetch_schedule` rather than
  at module load — pandas costs real startup time on every `fantasy`
  invocation. Keep it that way, and keep pandas out of `analysis/`: the model
  is numpy-only by choice.
- **Tests are plain assertion scripts, not pytest.** They print a summary and
  exit non-zero on failure. No network and no database *file* — `rules.py` and
  the report are tested against in-memory DuckDB fixtures.
  ```sh
  .venv/bin/python tests/run_all.py          # all ten, one line each
  .venv/bin/python tests/test_analysis.py    # or any one on its own
  ```
  The ten are `test_parse`, `test_analysis`, `test_report`, `test_names`,
  `test_rankings`, `test_dynatyze`, `test_angle`, `test_schedule`,
  `test_history`, `test_composite`. `test_composite` is the exception to "no
  database": it builds the real `schema.sql` in an in-memory DuckDB, because
  half of what it is checking is the round trip through the store.
- **Comments explain why, not what.** Docstrings are prose, not parameter lists.
  Match the surrounding density rather than annotating every line.
- **Calibration constants carry their reasoning** in a comment above them
  (see the top of `projection.py`). If you retune one, update the note and the
  calibration table in `docs/ALGORITHMS.md`.

## Do not

- Commit `data/` or `.env*` — both gitignored, and the DB is regenerable.
- Assume the nine standard categories. Read them from `rules.load`.
- Key anything on `stat_name`. Use `stat_id`.
- Re-implement "which side wins this category" at a comparison site. Call
  `query.beats`.
- Edit `AGENTS.md` and `CLAUDE.md` separately — `AGENTS.md` is a symlink to
  this file, so there is only one to edit.
- Re-run `fantasy auth login` to "fix" a 403.
- Report a simulated probability without the assumptions that produced it.

## Where the open work is

`docs/ALGORITHMS.md` ends with a prioritised list of what would improve the
model. The top item — pulling the NBA schedule — is **done**: `fantasy schedule
pull` populates `nba_schedule`, and `projection.team_schedule` fits each NBA
team's real games-per-week from it, replacing the old flat 3.5 assumption
(`games_per_week`/`--games` is now a fallback and an explicit override, not the
normal path). The next two, and the reasoning behind the order:

1. **Match the schedule to the actual fantasy week.** The snapshot has no
   week-number → date-range table, so `team_schedule` fits against the whole
   season rather than the specific week being analysed — a real bye week looks
   like any other week.
2. **Backtest against real weekly results** via `/league/{key}/scoreboard`.
   Nothing validates the probabilities today, which means every other
   improvement on the list is currently unmeasurable.

Issue #4 tracks pulling the league settings the model has to assume.
