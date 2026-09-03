# fantasy

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
├── templates/
│   └── app.html      # the interface
├── yahoo/
│   ├── auth.py       # OAuth 2.0, token file
│   ├── client.py     # authenticated API calls
│   └── parse.py      # Yahoo JSON → flat rows (pure functions)
└── store/
    ├── db.py         # DuckDB access
    └── schema.sql    # tables + views
```

`tests/test_parse.py` exercises the parsers against Yahoo-shaped fixtures with no network:

```sh
.venv/bin/python tests/test_parse.py
```

## Notes

DuckDB takes an **exclusive lock** on the database file. Two `fantasy` commands cannot run
at once, and an open `duckdb` shell will block a `pull`. Read-only commands (`sql`, `tables`,
`pulls`) open the file read-only and can share it.

Yahoo caps multi-entity requests at 25, so rosters, stats, and the free-agent pool are
fetched in batches; a full pull with all four stat periods makes a few hundred calls.
