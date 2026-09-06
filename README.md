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
fantasy report                       # one standing report, for you or an agent
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
| `fantasy report` | One standing markdown report over everything above. |
| `fantasy sql "<query>"` | Run ad-hoc SQL. |
| `fantasy rankings sources` | List the ranking sites this app knows how to scrape. |
| `fantasy rankings pull SOURCE` | Scrape a ranking site and append it to the database. |
| `fantasy rankings show SOURCE` | Show the latest pull for a ranking source; `--notes` for its written commentary. |
| `fantasy rankings composite build` | Fold every ranking source into one ordering and store it. |
| `fantasy rankings composite show` | Show the stored composite ranking. |
| `fantasy schedule pull [SEASON]` | Fetch the NBA game schedule and append it to the database. |
| `fantasy schedule show` | Show the latest pulled schedule, optionally filtered by team. |
| `fantasy history pull [SEASONS]` | Fetch the seasons not already stored and append them. |
| `fantasy history show [PLAYER]` | Show stored season stats per game, or what is stored. |

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

## External rankings

Independent of the Yahoo snapshot, `fantasy rankings` scrapes named ranking sites and
appends the result to DuckDB on its own history — useful for comparing the model's
output against outside opinion, or feeding a ranking into analysis later.

```sh
fantasy rankings sources               # sites this app knows how to scrape
fantasy rankings pull hashtag_dynasty  # fetch + parse + store
fantasy rankings show hashtag_dynasty  # the latest pull, ranked
fantasy rankings show hashtag_dynasty --notes   # ...and what it wrote about them
```

Three sources ship today: `hashtag_dynasty` and `dynatyze_dynasty`, both scrapes of a
page at a fixed address, and `angle_dynasty` — Angle Fantasy Basketball's Top 300 9-cat
list, three rankers plus a consensus average.

Angle is the awkward one, and the reason `rankings pull` has the machinery it does: each
edition is a new WordPress post embedding a new Google Sheet, so there is no permanent
URL to point at. `--url` accepts any of the four forms you might have to hand — the
rankings post, the embedded `pubhtml` link, a normal `/edit` sheet URL, or an
`output=csv` link — and rewrites it to the sheet's CSV export (following the post's
`<iframe>` when given an article). That URL is then remembered: the next
`fantasy rankings pull angle_dynasty` reuses it, so you only pass `--url` when a new
edition is published.

```sh
fantasy rankings pull angle_dynasty                      # the last URL pulled
fantasy rankings pull angle_dynasty --url <new post>     # ...until a new edition
```

Each Angle row also carries the sheet's own title (`Top 300 9-Cat Dynasty Rankings July
2026`) as `extra.edition`, alongside `average_rank`, each ranker's own number, and the
movement arrow — so a stored ranking still says which edition it came from after the URL
behind it has moved on.

### Commentary

Ranking sites sometimes publish a written note beside the number, and where one exists
it is stored on the row as `extra.outlook`:

```
#4 Nikola Jokic
  He's not 4th because he has regressed in any way or because I'm down on him. We just
  now have 3 comparable players who are a lot younger, and we have to factor in age
  when ranking players in dynasty.
```

Only **hashtag_dynasty** publishes any, and only for some players — 99 of 400 on the
September 2026 board, though 46 of the top 50. The other two carry none, and that is a
property of the sources rather than a gap in the scrapers: Angle's sheet is nine
columns of numbers with no prose in any of them, and Dynatyze's board has no notes
field in either its embedded JSON-LD or the sanctioned `dynasty-rankings.md` variant it
advertises for machine readers. Both parsers say so in their module docstrings so the
question does not have to be re-investigated.

```sql
SELECT rank, player_name, json_extract_string(extra, '$.outlook') AS note
FROM v_player_rankings
WHERE source = 'hashtag_dynasty' AND note IS NOT NULL
ORDER BY rank;
```

Each pull is matched against `v_players` by name and stamped with `player_key` where a
confident match is found (case/punctuation/suffix-insensitive, no fuzzy matching — a
genuine spelling mismatch is left unmatched rather than silently paired with the wrong
player). `fantasy rankings pull` reports how many rows matched; the rest are typically
players outside your league's snapshot rather than a matching bug.

A source is a pure `parse(text) -> list[dict]` function registered in
`fantasy/sources/rankings/__init__.py`; the network fetch is shared, and a source that
has to work out *where* to fetch from declares a `resolve` alongside its parser. Add a
new site by writing one module next to `fantasy/sources/rankings/hashtagbasketball.py`
and registering it — nothing else changes. Because each parser reads one site's actual
template, it is scrape code tied to a specific site's markup, not a generic table
scraper — expect it to need a one-file fix if that site redesigns its rankings page.

### One ranking out of several

Each source ranks the same players against a different depth and a different house
view. `fantasy rankings composite build` folds every source of the same kind into a
single ordering and appends it to the database; `show` reads it back.

```sh
fantasy rankings composite build              # recompute and append a run
fantasy rankings composite show               # the stored ordering, top 40
fantasy rankings composite show --team me     # ...restricted to your roster
fantasy rankings composite show --min-spread 40   # where the sources disagree most
```

```
 #   score  player             tm/age    angl  dyna  hash  owner
 11  88.3   Cameron Boozer     MEM 19.1  12    ~12   9     -
 17  80.9   Evan Mobley        CLE 25.2  21    18    15    *Red Eyes…
 88  33.7   Keegan Murray      SAC 26.0  114   off   70    *Red Eyes…
100  29.8   Ace Bailey         UTA 20.1  92    ·     104   *Red Eyes…
```

A rank becomes a value on a decay curve (#1 vs #10 is worth far more than #200 vs
#210) and the scores are averaged, but the ordering is decided by how *absence* is
read, and the table says which of the three cases each cell is:

- a number — the source ranked him there;
- `off` — the source's list is long enough that it saw him and left him off, so it
  votes just past its own end;
- `·` — the source's list is too short to reach him, so it abstains rather than
  voting against him;
- `~n` — the source's numbering has a slot with no row in it (dynatyze's markup
  drops 7 of its top 75), and this is a guess at who holds it, ranked by where the
  other sources put the players it omitted.

Draft picks that a source ranks inline with players (`2027 Early 1st`) keep their
slot but are held out of the rerank. Each run records the ranking pull ids and the
parameters behind it, so an old ordering stays readable after those pulls have been
superseded, and a rebuild appends rather than overwrites. The method, and the
reasoning for each rule, is in `fantasy/analysis/composite.py`.

```sql
-- Rankings joined against your roster
SELECT r.rank, r.player_name, r.team_abbr, p.selected_position
FROM v_player_rankings r
LEFT JOIN v_roster_players p USING (player_key)
WHERE r.source = 'hashtag_dynasty'
ORDER BY r.rank
LIMIT 20;
```

## NBA schedule

Independent of the Yahoo snapshot, `fantasy schedule` fetches the league-wide game
schedule (via [nba_api](https://github.com/swar/nba_api), stats.nba.com's own
`ScheduleLeagueV2` endpoint) and appends it to DuckDB on its own history. This
is the `(date, nba_team)` datasource `docs/ALGORITHMS.md` used to name as the
model's single biggest open gap; it is now wired in — `fantasy matchup` and
`fantasy waivers` fit each NBA team's real games-per-week from it instead of
assuming a flat league-wide number.

```sh
fantasy schedule pull            # season inferred from today's date
fantasy schedule pull 2026-27    # or pull a specific season explicitly
fantasy schedule show --team BOS
```

Team columns are Yahoo-style tricodes (`BOS`, `GSW`, ...), so the schedule joins
straight onto `players.editorial_team_abbr` with no lookup table. Preseason games are
dropped, as are Emirates NBA Cup semifinal/final placeholders before the group stage
that decides them has been played — those show up once a re-pull happens after the
teams are known.

`analysis/projection.py`'s `team_schedule` reads the most recently pulled season and
fits each team's weekly game count to a Binomial by matching its real mean and
variance across the season's weeks — a team with clustered back-to-backs gets a
wider spread than one with an even schedule. `--games` now only matters as a
fallback (no schedule pulled yet) or as an explicit override that flattens every
team back to one number, for a deliberate what-if.

```sql
-- Real games per NBA team for a date range (a fantasy week, say)
SELECT nba_team, count(*) AS games
FROM v_nba_team_schedule
WHERE game_date BETWEEN '2026-11-02' AND '2026-11-08'
GROUP BY 1 ORDER BY 2 DESC;
```

## Player history

A Yahoo snapshot holds one season, and once that season is over its four stat
windows collapse to identical full-season figures — so the store on its own
cannot say whether a player is climbing, declining, or has ever been durable.
`fantasy history` closes that gap: stats.nba.com's `LeagueDashPlayerStats`
(again via nba_api), season totals for every player who appeared, one pull per
season.

```sh
fantasy history pull                     # the 4 most recent played seasons
fantasy history pull -n 6                # or six of them
fantasy history pull 2019-20 2020-21     # or name them
fantasy history pull --refresh           # re-fetch even what is already stored
fantasy history show "Trae Young"        # per-game lines, one row per season
fantasy history show                     # what is stored, per season
```

**A season already stored is skipped.** A finished season's totals are final,
so there is nothing to gain by fetching it twice: miss a year and the next run
costs a request only for the years you missed. Two exceptions. The **season in
progress** is always re-fetched, because its totals are still accumulating and
a stored copy is a snapshot of a moving number. And `--refresh` overrides the
skip entirely — which is also how you re-match old seasons against a newer
league snapshot, since `player_key` is resolved at insert time and a season
stored before a `fantasy pull` still carries the matches it made then.

A refresh **appends**, like every other pull here; it does not overwrite. The
older rows stay in `nba_player_seasons` and `v_nba_player_seasons` resolves to
the newest successful pull for that season.

It is one request per season rather than one per player — the endpoint returns
the whole league at once, ~570 rows — so four seasons is four requests. Totals
are stored rather than per-game figures: per-game is a division by `gp` that
loses nothing, while nba.com's own PerGame mode rounds. `v_player_history` does
that division for you.

Rows are joined to the snapshot by name through the same `names.normalize()`
every outside source goes through, and an unmatched row is **stored with a null
`player_key` rather than dropped**. Most nulls are simply players Yahoo has no
row for; the reverse — a rostered player missing from a season — is the
interesting direction, and it means he did not play that year rather than that
the match failed.

Seasons resolve independently, so a season that fails (stats.nba.com throttles)
leaves the others intact and is worth re-running on its own.

```sql
-- Four-season trend for one player, per game
SELECT season, nba_team, gp, mpg, pts, reb, ast, tpm, stl, blk, tov, fg_pct, ft_pct
FROM v_player_history WHERE full_name = 'Cade Cunningham' ORDER BY season;

-- Who is trending up: last season's points per game against three years ago
SELECT full_name,
       max(pts) FILTER (season = '2025-26') - max(pts) FILTER (season = '2022-23') AS delta
FROM v_player_history GROUP BY 1 HAVING count(*) = 4 ORDER BY delta DESC LIMIT 10;
```

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

Ranking tables, on their own pull sequence (not tied to a `league_key`):

| Table | Contents |
|---|---|
| `ranking_pulls` | One row per `fantasy rankings pull`: source, URL, timestamp, status. |
| `player_rankings` | One row per (source, player): rank, name, team, positions, age, `player_key` if matched, and source-specific fields as JSON in `extra`. |

`v_player_rankings` resolves to the latest successful pull per source.

Composite tables, derived from those rankings rather than pulled, on the same
append-only footing:

| Table | Contents |
|---|---|
| `composite_runs` | One row per `fantasy rankings composite build`: kind, timestamp, status, the ranking pull ids folded in and the parameters used, both as JSON. |
| `composite_rankings` | One row per player per run, already in composite order: score, consensus, spread, and each source's vote as JSON in `votes`. |

`v_composite_rankings` resolves to the newest successful run per kind.

NBA schedule tables, on their own pull sequence (keyed by `season`, not `league_key`):

| Table | Contents |
|---|---|
| `nba_schedule_pulls` | One row per `fantasy schedule pull`: season, timestamp, status. |
| `nba_schedule` | One row per game: date, home/away team tricode, cup/exhibition label. |

`v_nba_schedule` resolves to the latest successful pull per season; `v_nba_team_schedule`
unpivots it to one row per (team, game) — the join surface for counting a team's games in
a date range.

NBA player-season tables, on their own pull sequence (also keyed by `season`):

| Table | Contents |
|---|---|
| `nba_season_pulls` | One row per season fetched by `fantasy history pull`: season, timestamp, status. |
| `nba_player_seasons` | One row per (player, season): season totals, age, games, `player_key` if matched. Wide, not long like `player_stats` — nba.com's columns are fixed by the endpoint rather than by a league's settings. |

`v_nba_player_seasons` resolves to the latest successful pull per season;
`v_player_history` divides those totals by games and restricts them to the players in
the current league snapshot.

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
Red Eyes Black Dragon vs Guan Yu  10,000 simulated weeks, 3.20 games/team

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
(override the schedule-fit NBA games per team per week with one flat number).

### The report

```sh
fantasy report                    # overwrites reports/summary.md
fantasy report --out -            # to stdout instead
fantasy report --out week23.md    # a dated copy, kept alongside it
```

By default every run overwrites the same `reports/summary.md`, so there is
always one current report at a known path — the right default for something an
agent reads without knowing which week it is. Pass `--out` with a name of your
own to keep a dated history instead; `reports/` is gitignored either way.

`fantasy report` composes the whole picture into one markdown document: your
roster, your category profile against the league, the standings, the waiver
board, the model's assumptions, and — the part that makes it more than a dump —
**a generated list of what to go research**, ranked by where the model is least
certain. A player with an eleven-game sample sitting on IL is exactly where an
injury report changes the answer, and the report says so by name.

It is built to be handed to an agent that will pair it with news the snapshot
cannot contain. Every table names its units, every probability arrives with the
assumptions behind it, and the front-matter carries `report_version` plus
machine-readable `data_quality` codes so a reader can branch on what is wrong
with the snapshot without parsing prose.

Progress and errors go to stderr, so `fantasy report --out - > week.md` yields a
clean document.

### The model

A week is simulated per player and summed:

| Step | How |
|---|---|
| Per-game rate | Recency-weighted blend of the season/30/14/7-day windows, weighting each window by the games in it. |
| Games played | `Binomial(n, p)`, `n` and `p` fit per NBA team to the real pulled schedule; `p` also folds in Yahoo injury status and games missed so far. |
| Usage | One draw per player per week, shared across their categories, so points, rebounds and assists move together. Its spread widens as the sample behind the rate shrinks. |
| Counting stats | Gamma matched to a per-game variance of `mean + (cv × mean)²` — a Poisson floor for rare events plus a proportional term for volume. |
| FG% / FT% | Attempts drawn, then makes as `Binomial(attempts, form)`; team percentages pool real makes over real attempts, the way Yahoo scores them. |

Every player is drawn **once** into a column, so a lineup is a set of columns to
add up and a swap is one vector subtract and one add. Candidates are therefore
scored against identical simulated weeks, and a reported gain is a real
difference rather than two noisy numbers subtracted — top moves hold to ±0.01
categories across seeds.

One thing the snapshot cannot tell it, surfaced as an option rather than
hidden: there are no game logs, so per-game variance comes from the calibrated
model above rather than from a player's own history. Games per week used to be
a second such gap; it is now fit per NBA team from the real pulled schedule
(`--games` overrides it with one flat number, for a deliberate what-if) — though
that fit is still against a *typical* week of the season rather than the
specific dates of the current fantasy week, since the snapshot has no
week-number-to-date-range table.

The knobs live at the top of `fantasy/analysis/projection.py` — recency weights,
per-category spread, and the availability table by injury status.

**[docs/ALGORITHMS.md](docs/ALGORITHMS.md)** documents all of it properly: every
formula, how the constants were calibrated, a variance decomposition showing
which categories are decided by the schedule and which by noise, and the
limitations worth knowing before you trust a number — and a prioritised list of
what would make the simulation better, led by matching the real schedule to
the specific fantasy week and backtesting against real weekly results.

**[docs/LEAGUES.md](docs/LEAGUES.md)** is the other half: the settings Yahoo does
not return, written down by hand. Lineup lock, acquisition limits, keeper rules
and playoff shape are all things `fantasy rules` has to assume — that file is
where the real answers go, one block per league, with `?` marking what is still
unknown so it reads as a gap rather than a default.

### From Python

Each entry point takes an open connection and returns plain dicts:

```python
from fantasy.store import db
from fantasy.analysis import composite, matchup, waiver

with db.connect(read_only=True) as con:
    report = matchup.head_to_head(con, team_b="Guan Yu", sims=20000)
    print(report["categories"][0]["p_win"])

    moves = waiver.add_drop(con, opponent="Starboy")
    print(moves["moves"][0]["add"]["name"], moves["moves"][0]["delta_cats"])

    board = composite.load(con)          # the stored composite; build() recomputes
    print(board["players"][0]["player_name"], board["players"][0]["score"])
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
├── composite.py      # fold every ranking source into one ordering, append to DuckDB
├── names.py          # normalize() — the join key between an outside name and a Yahoo one
├── pull.py           # snapshot orchestration
├── query.py          # read-side queries over the latest snapshot
├── rankings.py       # scrape a ranking site, match players, append to DuckDB
├── report.py         # composes the whole picture into one markdown document
├── schedule.py       # fetch the NBA game schedule, append to DuckDB
├── history.py        # fetch past-season NBA player stats, append to DuckDB
├── server.py         # local JSON API + app host
├── analysis/
│   ├── rules.py      # league rules read from the snapshot; refuses what it can't model
│   ├── projection.py # player -> weekly rates, variance, availability
│   ├── simulate.py   # Monte Carlo engine, one column per player
│   ├── matchup.py    # head-to-head and against-the-field odds
│   ├── waiver.py     # free-agent add/drop search
│   └── composite.py  # many ranking sources -> one ordering, and reading it back
├── sources/          # everything pulled in besides your Yahoo league
│   ├── rankings/
│   │   ├── fetch.py             # shared HTTP GET for ranking sites
│   │   ├── hashtagbasketball.py # pure HTML → rows parser, one file per site
│   │   ├── dynatyze.py          # pure JSON-LD → rows parser
│   │   └── angle.py             # Google Sheet CSV → rows, plus the URL rewriting
│   │                            # that finds the sheet behind a rankings post
│   ├── schedule/
│   │   ├── client.py # fetch the schedule from stats.nba.com (via nba_api)
│   │   └── parse.py  # raw payload → flat rows (pure functions)
│   └── history/
│       ├── client.py # fetch past-season player totals from stats.nba.com
│       └── parse.py  # raw payload → flat rows (pure functions)
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
├── ALGORITHMS.md     # the model, its calibration, and its limits
└── LEAGUES.md        # each league's real settings, written down by hand
```

`tests/test_parse.py` exercises the parsers against Yahoo-shaped fixtures,
`tests/test_analysis.py` the simulation math against hand-built players,
`tests/test_report.py` the report's formatting and derivations against a fixture
document, `tests/test_names.py` the name standardizer, `tests/test_rankings.py`,
`tests/test_dynatyze.py` and `tests/test_angle.py` each ranking source against a
saved fixture of what that site really serves (plus, for Angle, the sheet-URL
rewriting), `tests/test_schedule.py` the schedule parser against a ScheduleLeagueV2-shaped
fixture, `tests/test_history.py` the player-totals parser and which seasons a run
asks for, and `tests/test_composite.py` the composite's folding rules and its round
trip through the store. None touches the network; only the last touches a
database, and that one is in-memory:

```sh
.venv/bin/python tests/run_all.py          # all of them, one line each
.venv/bin/python tests/test_analysis.py    # or any one on its own
```

## Notes

DuckDB takes an **exclusive lock** on the database file. Two `fantasy` commands cannot run
at once, and an open `duckdb` shell will block a `pull`. Read-only commands (`sql`, `tables`,
`pulls`) open the file read-only and can share it.

Yahoo caps multi-entity requests at 25, so rosters, stats, and the free-agent pool are
fetched in batches; a full pull with all four stat periods makes a few hundred calls.
