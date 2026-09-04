# Working in this repo

`fantasy` is a CLI that snapshots a Yahoo Fantasy NBA league into DuckDB and runs
analysis over it. Two halves: a **pull** side (Yahoo → DuckDB, append-only) and a
**read** side (queries, a local web view, and a Monte Carlo model of a fantasy week).

Read [README.md](README.md) for what the commands do and
[docs/ALGORITHMS.md](docs/ALGORITHMS.md) for how the model works and what it
cannot do. This file is the part that is not obvious from the code.

## Before you do anything

**Use the venv.** `.venv/bin/python`, `.venv/bin/fantasy`. There is no global install.

**DuckDB takes an exclusive lock on the file.** Only one writer at a time. Two
`fantasy` commands cannot run concurrently, and an open `duckdb` shell blocks a
`pull`. Read-only commands (`sql`, `tables`, `pulls`, `rules`, `matchup`,
`waivers`, `view`) open the file read-only and *can* share it. Do not fan
analysis out across parallel shells expecting them to interleave — run them in
sequence.

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
   and conclude it is broken.
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
.venv/bin/fantasy report > week.md      # the whole picture, for an agent to read
```

The rest of the CLI answers narrower questions:

```sh
.venv/bin/fantasy rules                      # what the model reads vs assumes
.venv/bin/fantasy matchup "Guan Yu"          # per-category odds against one team
.venv/bin/fantasy matchup                    # against all 11 opponents
.venv/bin/fantasy waivers --vs Starboy       # add/drops for one matchup
.venv/bin/fantasy sql "select * from v_my_team"
```

Teams resolve loosely — team key, team id (`8`), or part of a name or manager.

For anything the CLI does not already print, **call the Python API rather than
parsing terminal output**. Every entry point takes an open connection and
returns plain dicts:

```python
from fantasy.store import db
from fantasy.analysis import matchup, projection, rules, waiver

with db.connect(read_only=True) as con:
    rules.load(con)                                   # refuses leagues it can't model
    matchup.head_to_head(con, team_b="Guan Yu", sims=20000)
    matchup.versus_field(con)
    waiver.add_drop(con, opponent="Starboy", sims=8000)
    projection.build(con)                             # per-player rates, before simulation
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
├── cli.py            Typer commands; rendering only, no logic
├── pull.py           snapshot orchestration; a failed step is recorded, the rest continues
├── query.py          read-side queries over the latest snapshot
├── server.py         stdlib HTTP + JSON for `fantasy view`
├── yahoo/            auth, client, parse (pure functions, no I/O)
├── store/            db.py + schema.sql
└── analysis/
    ├── rules.py      league rules from the snapshot; runs first, refuses what it can't model
    ├── projection.py player -> per-game rates, variance, availability
    ├── simulate.py   Monte Carlo; one column per player
    ├── matchup.py    head-to-head and against-the-field
    └── waiver.py     add/drop search + lineup legality
```

- **The store is append-only.** Nothing is ever UPDATEd or DELETEd. `v_*` views
  resolve to the newest successful pull. Keep it that way — accumulated history
  is the basis for several planned improvements.
- **Parsers are pure.** `yahoo/parse.py` takes Yahoo-shaped dicts and returns
  flat rows, no network. That is why it is testable.
- **Analysis returns plain dicts.** The CLI, the JSON server and a REPL all use
  the same calls. Do not put formatting in the analysis modules.
- **Nothing about the league is hardcoded.** Categories, the inverted category
  and roster slots come from the snapshot via `rules.py`. If you add a scored
  quantity, add it to `rules.SIMULATED` (keyed by Yahoo stat id) or the run will
  correctly refuse.
- **Simulate once, reuse the columns.** `simulate.draw` gives a
  `(sims × players)` array per category; a lineup is a set of columns to sum and
  a swap is `− column[drop] + column[add]`. If you find yourself re-simulating
  to evaluate a variant, you are doing it the slow and noisy way.

## Conventions

- **Dependencies are deliberately few** — duckdb, numpy, typer, rich,
  requests-oauthlib, python-dotenv. The web layer is stdlib on purpose. Do not
  add pandas/scipy/flask without asking; the analysis is numpy-only by choice.
- **Tests are plain assertion scripts, not pytest.** They print a summary and
  exit non-zero on failure. No network, no database — `rules.py` is tested
  against in-memory DuckDB fixtures.
  ```sh
  .venv/bin/python tests/test_parse.py
  .venv/bin/python tests/test_analysis.py
  ```
- **Comments explain why, not what.** Docstrings are prose, not parameter lists.
  Match the surrounding density rather than annotating every line.
- **Calibration constants carry their reasoning** in a comment above them
  (see the top of `projection.py`). If you retune one, update the note and the
  calibration table in `docs/ALGORITHMS.md`.

## Do not

- Commit `data/` or `.env*` — both gitignored, and the DB is regenerable.
- Assume the nine standard categories. Read them from `rules.load`.
- Key anything on `stat_name`. Use `stat_id`.
- Re-run `fantasy auth login` to "fix" a 403.
- Report a simulated probability without the assumptions that produced it.

## Where the open work is

`docs/ALGORITHMS.md` ends with a prioritised list of what would improve the
model. The top two, and the reasoning behind the order:

1. **Pull the NBA schedule.** 44–49% of the variance in the volume categories is
   *how many games get played*, currently a flat 3.5 assumption.
2. **Backtest against real weekly results** via `/league/{key}/scoreboard`.
   Nothing validates the probabilities today, which means every other
   improvement on the list is currently unmeasurable.

Issue #4 tracks pulling the league settings the model has to assume.
