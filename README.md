# FantasyGPT

A command-line tool that pulls your Yahoo Fantasy NBA league's current state into a
[DuckDB](https://duckdb.org) database so you can query it with SQL.

Each run appends a **snapshot** — league settings, every team, every roster, the free-agent
pool, and per-player stat splits — stamped with a pull id and timestamp. Nothing is
overwritten, so you accumulate week-over-week history for free. `v_*` views always resolve
to the most recent pull.

## Setup

### 1. Register a Yahoo application

At [developer.yahoo.com/apps](https://developer.yahoo.com/apps/), create an app with:

| Field | Value |
|---|---|
| Application Type | **Installed Application** |
| Redirect URI | `https://localhost` |
| API Permissions | Fantasy Sports — Read |

### 2. Configure and install

```sh
cp .env.example .env      # then fill in your client id and secret
python3 -m venv .venv
.venv/bin/pip install -e .
```

### 3. Authenticate

```sh
fantasy auth login
```

This prints a Yahoo consent URL. Approve it in a browser; Yahoo redirects to
`https://localhost`, which will not load — that is expected. Copy the full URL out of the
address bar and paste it back at the prompt.

Tokens are written to `~/.fantasy/token.json` (mode `600`) and refreshed automatically.
They are deliberately kept **out of** the database, which holds only league data.

## Usage

```sh
fantasy leagues                      # list the leagues on your account
fantasy pull                         # snapshot your league (or pass a league key)
fantasy pull 466.l.28641 --skip-stats
fantasy sql "select * from v_my_team"
fantasy view                         # open the league interface in your browser
fantasy rules                        # what the model reads, and what it assumes
fantasy matchup "Guan Yu"            # your odds in each category against them
fantasy waivers                      # free-agent pickups ranked by odds bought
```

| Command | Description |
|---|---|
| `fantasy auth login` | Authorize this machine against Yahoo. |
| `fantasy auth status` | Show credential/token state and confirm the API responds. |
| `fantasy auth logout` | Delete the stored token. |
| `fantasy leagues` | List your NBA leagues and their league keys. |
| `fantasy pull [LEAGUE_KEY]` | Snapshot a league. Omit the key if you only have one. |
| `fantasy pulls` | List past pulls with status and timestamps. |
| `fantasy tables` | Every table and view with row counts. |
| `fantasy view` | Launch the league interface in your browser. |
| `fantasy rules` | League rules the model runs under, and what it had to assume. |
| `fantasy matchup [TEAM]` | Win probability per category against a team, or the whole league. |
| `fantasy waivers` | Rank free-agent add/drops by how much they move the odds. |
| `fantasy sql "<query>"` | Run ad-hoc SQL. |

`pull` options: `--skip-stats` (much faster), `--periods season,last_7,last_14,last_30`,
`--fa-limit N` (cap the free-agent pool; default is the whole pool).

### The interface

`fantasy view` starts a local read-only server and opens a single page with four
views, switched in the UI rather than by CLI flags:

| View | What it shows |
|---|---|
| **Roster** | Any team's players across the nine categories, plus a team strength strip. |
| **Standings** | Every team's weekly output per category, with a rank in each. |
| **Free agents** | The available pool, filterable by position. |
| **Compare** | Two teams side by side with the category-by-category edge. |

Cells are shaded by that player's percentile among every rostered player in the
league — **turnovers inverted**, so green always means good. `△` marks players
under 20 games, where a per-game rate is noise.

Options: `--port 8777`, `--no-open`. The snapshot is opened **read-only**, so
other `fantasy` commands and a `duckdb` shell still work while it runs.

Behind it is a small JSON API, useful on its own:

```
GET /api/meta                          league, teams, periods, pull info
GET /api/roster?team=<key>&period=…    one team's players with percentiles
GET /api/standings?period=…            every team's category output and ranks
GET /api/free-agents?period=…          the available pool
GET /api/compare?a=<key>&b=<key>       head-to-head across the nine categories
```

A failing step is recorded against the pull and the rest continues, so a single bad roster
call does not lose the snapshot. Such a pull is marked `partial`.

## Schema

Snapshot tables — every row carries `pull_id` and `league_key`:

| Table | Contents |
|---|---|
| `pulls` | One row per run: timestamp, status, error note. |
| `leagues` | Name, season, week, team count, scoring type. |
| `league_settings` | Playoff structure, waivers, FAAB, draft type. |
| `league_stat_categories` | The league's scoring categories. |
| `league_roster_positions` | Roster slots and counts. |
| `teams` | Every team, manager, record, standing, `is_my_team`. |
| `players` | Player attributes: name, NBA team, eligible positions, injury status, birth date. |
| `rosters` | Which player is on which team, in which slot. Free agents have `is_free_agent = true`. |
| `player_stats` | **Long format** — one row per (player, period, stat). |

`player_stats` is long rather than one column per category on purpose: leagues differ in
their scoring categories and Yahoo adds stat ids, so a wide table would need a migration
every time. Use DuckDB's `PIVOT` when you want it wide.

Views resolving to the latest pull: `v_leagues`, `v_league_settings`, `v_stat_categories`,
`v_roster_positions`, `v_teams`, `v_players`, `v_rosters`, `v_player_stats`,
`v_roster_players`, `v_my_team`, `v_free_agents`.

## Analysis

Two commands sit on top of a Monte Carlo model of a fantasy week. Both simulate
thousands of weeks, so every number is a probability rather than a projection.

### Benchmarking against another team

```sh
fantasy matchup "Guan Yu"          # one opponent
fantasy matchup                    # every opponent at once
fantasy matchup 8 --sims 50000     # by team id, more precision
```

```
Red Eyes Black Dragon vs Guan Yu  10,000 simulated weeks, 3.5 games/team

 cat   Red Eyes Black Dra   Guan Yu   win
 PTS   630.9                635.7      48.4%   ######......
 REB   217.9                232.8      36.4%   ####........
 AST   135.7                151.4      30.0%   ####........
 ...
Expected score 3.8 of 9 categories   |   matchup 33.8% win, 0.0% tie, 66.2% loss
```

The no-argument form runs your week against all eleven opponents and sorts them
hardest first — the fastest way to see which categories you are structurally
losing rather than losing to one particular roster.

### Simulating free-agent pickups

```sh
fantasy waivers                    # best add/drops against the league
fantasy waivers --vs Starboy       # optimise for one matchup
fantasy waivers --by-player        # one row per free agent, with their best drop
```

Every free agent is paired with every plausible drop, and the pair is scored by
the change in **expected categories won per week**. Drop candidates are not
guessed at: each of your own players is first priced by what the team loses
without them, and only the cheapest are offered up. Illegal results are filtered
— a swap that leaves you unable to fill the starting lineup never appears.

Both commands share options: `--sims`, `--seed`, `--team` (analyse someone
else's roster), `--periods` (which stat windows to blend), and `--games`
(NBA games per team per week).

### The model

A week is simulated per player and summed:

| Step | How |
|---|---|
| Per-game rate | Recency-weighted blend of the season/30/14/7-day windows, weighting each window by the games in it. |
| Games played | `Binomial(4, p)`, where `p` folds in Yahoo injury status and games missed so far. |
| Usage | One draw per player per week, shared across their categories, so points, rebounds and assists move together. Its spread widens as the sample behind the rate shrinks. |
| Counting stats | Gamma matched to a per-game variance of `mean + (cv × mean)²` — a Poisson floor for rare events plus a proportional term for volume. |
| FG% / FT% | Attempts drawn, then makes as `Binomial(attempts, form)`; team percentages pool real makes over real attempts, the way Yahoo scores them. |

Every player is drawn **once** into a column, so a lineup is a set of columns to
add up and a swap is one vector subtract and one add. Candidates are therefore
scored against identical simulated weeks, and a reported gain is a real
difference rather than two noisy numbers subtracted — top moves hold to ±0.01
categories across seeds.

Two things the snapshot cannot tell it, both surfaced as options rather than
hidden: there are no game logs, so per-game variance comes from the calibrated
model above rather than from a player's own history; and there is no NBA
schedule, so `--games` defaults to the league-wide average of 3.5 rather than
counting each team's real games that week.

The knobs live at the top of `fantasy/analysis/projection.py` — recency weights,
per-category spread, and the availability table by injury status.

**[docs/ALGORITHMS.md](docs/ALGORITHMS.md)** documents all of it properly: every
formula, how the constants were calibrated, a variance decomposition showing
which categories are decided by the schedule and which by noise, and the
limitations worth knowing before you trust a number — and a prioritised list of
what would make the simulation better, led by pulling the real NBA schedule.

### From Python

Each entry point takes an open connection and returns plain dicts:

```python
from fantasy.store import db
from fantasy.analysis import matchup, waiver

with db.connect(read_only=True) as con:
    report = matchup.head_to_head(con, team_b="Guan Yu", sims=20000)
    print(report["categories"][0]["p_win"])

    moves = waiver.add_drop(con, opponent="Starboy")
    print(moves["moves"][0]["add"]["name"], moves["moves"][0]["delta_cats"])
```

### Example queries

```sql
-- My roster
SELECT full_name, selected_position, positions, status FROM v_my_team;

-- Standings
SELECT standing, name, manager_name, wins, losses FROM v_teams ORDER BY standing;

-- Top free agents by last-14-day scoring
SELECT p.full_name, s.value AS pts
FROM v_free_agents p
JOIN v_player_stats s USING (league_key, player_key)
WHERE s.stat_period = 'last_14' AND s.stat_name = 'PTS'
ORDER BY pts DESC LIMIT 20;

-- Wide stat table for the season
PIVOT (SELECT player_key, stat_name, value FROM v_player_stats WHERE stat_period = 'season')
ON stat_name USING first(value);

-- What changed on my roster between the two most recent pulls
SELECT pull_id, player_key FROM rosters
WHERE team_key = (SELECT team_key FROM v_teams WHERE is_my_team)
  AND pull_id IN (SELECT pull_id FROM pulls ORDER BY pull_id DESC LIMIT 2);
```

## Layout

```
fantasy/
├── cli.py            # Typer commands
├── config.py         # env + paths
├── pull.py           # snapshot orchestration
├── query.py          # read-side queries over the latest snapshot
├── server.py         # local JSON API + app host
├── analysis/
│   ├── rules.py      # league rules read from the snapshot; refuses what it can't model
│   ├── projection.py # player -> weekly rates, variance, availability
│   ├── simulate.py   # Monte Carlo engine, one column per player
│   ├── matchup.py    # head-to-head and against-the-field odds
│   └── waiver.py     # free-agent add/drop search
├── templates/
│   └── app.html      # the interface
├── yahoo/
│   ├── auth.py       # OAuth 2.0, token file
│   ├── client.py     # authenticated API calls
│   └── parse.py      # Yahoo JSON → flat rows (pure functions)
└── store/
    ├── db.py         # DuckDB access
    └── schema.sql    # tables + views

docs/
└── ALGORITHMS.md     # the model, its calibration, and its limits
```

`tests/test_parse.py` exercises the parsers against Yahoo-shaped fixtures, and
`tests/test_analysis.py` the simulation math against hand-built players. Neither
touches the network or the database:

```sh
.venv/bin/python tests/test_parse.py
.venv/bin/python tests/test_analysis.py
```

## Notes

DuckDB takes an **exclusive lock** on the database file. Two `fantasy` commands cannot run
at once, and an open `duckdb` shell will block a `pull`. Read-only commands (`sql`, `tables`,
`pulls`) open the file read-only and can share it.

Yahoo caps multi-entity requests at 25, so rosters, stats, and the free-agent pool are
fetched in batches; a full pull with all four stat periods makes a few hundred calls.
