-- Append-only snapshot store.
--
-- Every row belongs to a `pull`. Nothing is ever UPDATEd or DELETEd, so the tables
-- accumulate history; the v_* views resolve to the newest successful pull per league.

CREATE SEQUENCE IF NOT EXISTS pull_id_seq START 1;

CREATE TABLE IF NOT EXISTS pulls (
    pull_id     BIGINT PRIMARY KEY,
    league_key  VARCHAR NOT NULL,
    pulled_at   TIMESTAMP NOT NULL,
    status      VARCHAR NOT NULL,           -- running | success | partial | error
    note        VARCHAR
);

CREATE TABLE IF NOT EXISTS leagues (
    pull_id       BIGINT NOT NULL,
    league_key    VARCHAR NOT NULL,
    league_id     VARCHAR,
    name          VARCHAR,
    season        INTEGER,
    num_teams     INTEGER,
    scoring_type  VARCHAR,
    current_week  INTEGER,
    start_date    VARCHAR,
    end_date      VARCHAR,
    is_finished   BOOLEAN,
    url           VARCHAR
);

CREATE TABLE IF NOT EXISTS league_settings (
    pull_id            BIGINT NOT NULL,
    league_key         VARCHAR NOT NULL,
    playoff_start_week INTEGER,
    num_playoff_teams  INTEGER,
    max_teams          INTEGER,
    waiver_type        VARCHAR,
    trade_end_date     VARCHAR,
    draft_type         VARCHAR,
    uses_playoff       BOOLEAN,
    uses_faab          BOOLEAN
);

CREATE TABLE IF NOT EXISTS league_stat_categories (
    pull_id         BIGINT NOT NULL,
    league_key      VARCHAR NOT NULL,
    stat_id         VARCHAR,
    name            VARCHAR,
    display_name    VARCHAR,
    sort_order      INTEGER,
    is_only_display BOOLEAN
);

CREATE TABLE IF NOT EXISTS league_roster_positions (
    pull_id       BIGINT NOT NULL,
    league_key    VARCHAR NOT NULL,
    position      VARCHAR,
    position_type VARCHAR,
    count         INTEGER
);

CREATE TABLE IF NOT EXISTS teams (
    pull_id      BIGINT NOT NULL,
    league_key   VARCHAR NOT NULL,
    team_key     VARCHAR,
    team_id      VARCHAR,
    name         VARCHAR,
    manager_name VARCHAR,
    is_my_team   BOOLEAN,
    wins         INTEGER,
    losses       INTEGER,
    ties         INTEGER,
    standing     INTEGER,
    moves        INTEGER,
    trades       INTEGER,
    logo_url     VARCHAR
);

CREATE TABLE IF NOT EXISTS players (
    pull_id             BIGINT NOT NULL,
    league_key          VARCHAR NOT NULL,
    player_key          VARCHAR,
    player_id           VARCHAR,
    full_name           VARCHAR,
    first_name          VARCHAR,
    last_name           VARCHAR,
    editorial_team_abbr VARCHAR,
    positions           VARCHAR[],
    display_position    VARCHAR,
    status              VARCHAR,
    injury_note         VARCHAR,
    birth_date          VARCHAR,
    uniform_number      VARCHAR,
    percent_owned       DOUBLE
);

CREATE TABLE IF NOT EXISTS rosters (
    pull_id           BIGINT NOT NULL,
    league_key        VARCHAR NOT NULL,
    team_key          VARCHAR,
    player_key        VARCHAR,
    selected_position VARCHAR,
    is_free_agent     BOOLEAN
);

-- Long format: one row per (player, period, stat). A league changing its scoring
-- categories never requires a schema migration; use PIVOT for a wide view.
CREATE TABLE IF NOT EXISTS player_stats (
    pull_id     BIGINT NOT NULL,
    league_key  VARCHAR NOT NULL,
    player_key  VARCHAR,
    player_id   VARCHAR,
    stat_period VARCHAR,
    stat_id     VARCHAR,
    stat_name   VARCHAR,
    value       DOUBLE,
    raw_value   VARCHAR
);

-- External player rankings, pulled from sites named in fantasy/sources/. Kept on its
-- own pull sequence, separate from `pulls`/league snapshot tables, because a ranking
-- pull happens on its own cadence and isn't tied to a specific Yahoo league.
CREATE SEQUENCE IF NOT EXISTS ranking_pull_id_seq START 1;

CREATE TABLE IF NOT EXISTS ranking_pulls (
    ranking_pull_id BIGINT PRIMARY KEY,
    source          VARCHAR NOT NULL,
    source_url      VARCHAR NOT NULL,
    pulled_at       TIMESTAMP NOT NULL,
    status          VARCHAR NOT NULL,        -- running | success | error
    note            VARCHAR
);

-- One row per (source, player) per pull. player_key is resolved by matching
-- player_name against v_players at pull time and is NULL when nothing matched.
-- player_name_key is the exact string that lookup was done on — fantasy.names
-- .normalize(player_name), stored so an unmatched row can be debugged with plain
-- SQL instead of re-running the Python normalizer.
CREATE TABLE IF NOT EXISTS player_rankings (
    ranking_pull_id BIGINT NOT NULL,
    source          VARCHAR NOT NULL,
    rank            INTEGER,
    player_name     VARCHAR,
    player_name_key VARCHAR,
    player_key      VARCHAR,
    team_abbr       VARCHAR,
    positions       VARCHAR[],
    age             DOUBLE,
    extra           VARCHAR                  -- source-specific fields as a JSON object
);

-- player_name_key was added after player_rankings already existed in some databases;
-- CREATE TABLE IF NOT EXISTS above is a no-op against those, so bring them up to date
-- explicitly rather than silently dropping the column on every insert from here on.
ALTER TABLE player_rankings ADD COLUMN IF NOT EXISTS player_name_key VARCHAR;

-- name_key() standardizes a name for matching or search: lowercase, accents folded to
-- ASCII, punctuation and a Jr./Sr./II-V suffix dropped. It mirrors the first two-thirds
-- of fantasy.names.normalize() in pure SQL so it works from any DuckDB session — a
-- macro, unlike a Python UDF, needs no per-connection registration to be queryable.
-- It deliberately stops short of normalize()'s nickname table (e.g. Nic/Nicolas):
-- that's a matching-time judgment call, not a property of the name itself, and stays
-- in fantasy/rankings.py where a wrong guess can be reviewed rather than baked into
-- every query. Keep the two in sync if either changes.
CREATE OR REPLACE MACRO name_key(name) AS
    regexp_replace(
        trim(
            regexp_replace(
                regexp_replace(lower(strip_accents(name)), '[.''-]', '', 'g'),
                '\b(jr|sr|ii|iii|iv|v)\b', '', 'g'
            )
        ),
        '\s+', ' ', 'g'
    );

-- --- Views: the newest successful pull per league ---

CREATE OR REPLACE VIEW latest_pull AS
SELECT league_key, max(pull_id) AS pull_id
FROM pulls
WHERE status IN ('success', 'partial')
GROUP BY league_key;

CREATE OR REPLACE VIEW v_leagues AS
SELECT l.* FROM leagues l JOIN latest_pull p USING (league_key, pull_id);

CREATE OR REPLACE VIEW v_league_settings AS
SELECT s.* FROM league_settings s JOIN latest_pull p USING (league_key, pull_id);

CREATE OR REPLACE VIEW v_stat_categories AS
SELECT c.* FROM league_stat_categories c JOIN latest_pull p USING (league_key, pull_id);

CREATE OR REPLACE VIEW v_roster_positions AS
SELECT r.* FROM league_roster_positions r JOIN latest_pull p USING (league_key, pull_id);

CREATE OR REPLACE VIEW v_teams AS
SELECT t.* FROM teams t JOIN latest_pull p USING (league_key, pull_id);

CREATE OR REPLACE VIEW v_players AS
SELECT pl.*, name_key(pl.full_name) AS full_name_key
FROM players pl JOIN latest_pull p USING (league_key, pull_id);

CREATE OR REPLACE VIEW v_rosters AS
SELECT r.* FROM rosters r JOIN latest_pull p USING (league_key, pull_id);

CREATE OR REPLACE VIEW v_player_stats AS
SELECT s.* FROM player_stats s JOIN latest_pull p USING (league_key, pull_id);

-- Rostered players with their team and owner attached.
CREATE OR REPLACE VIEW v_roster_players AS
SELECT
    r.league_key,
    t.name         AS team_name,
    t.manager_name,
    t.is_my_team,
    r.team_key,
    r.selected_position,
    p.player_key,
    p.full_name,
    p.full_name_key,
    p.editorial_team_abbr,
    p.positions,
    p.status,
    p.injury_note,
    p.birth_date
FROM v_rosters r
JOIN v_players p USING (league_key, player_key)
LEFT JOIN v_teams t USING (league_key, team_key)
WHERE NOT r.is_free_agent;

CREATE OR REPLACE VIEW v_my_team AS
SELECT * FROM v_roster_players WHERE is_my_team;

CREATE OR REPLACE VIEW v_free_agents AS
SELECT
    r.league_key,
    p.player_key,
    p.full_name,
    p.full_name_key,
    p.editorial_team_abbr,
    p.positions,
    p.status,
    p.injury_note,
    p.percent_owned
FROM v_rosters r
JOIN v_players p USING (league_key, player_key)
WHERE r.is_free_agent;

-- --- Views: the newest successful pull per ranking source ---

CREATE OR REPLACE VIEW latest_ranking_pull AS
SELECT source, max(ranking_pull_id) AS ranking_pull_id
FROM ranking_pulls
WHERE status = 'success'
GROUP BY source;

CREATE OR REPLACE VIEW v_player_rankings AS
SELECT r.* FROM player_rankings r JOIN latest_ranking_pull p USING (source, ranking_pull_id);

-- --- NBA schedule ---
--
-- A separate append-only source from the Yahoo pulls above: nba.com's own
-- schedule, keyed by NBA season rather than league_key. Same accumulate-history
-- shape as `pulls`/`leagues` — nothing UPDATEd or DELETEd, v_nba_schedule
-- resolves to the newest successful pull per season.

CREATE SEQUENCE IF NOT EXISTS nba_schedule_pull_id_seq START 1;

CREATE TABLE IF NOT EXISTS nba_schedule_pulls (
    pull_id    BIGINT PRIMARY KEY,
    season     VARCHAR NOT NULL,      -- e.g. '2026-27'
    pulled_at  TIMESTAMP NOT NULL,
    status     VARCHAR NOT NULL,      -- running | success | error
    note       VARCHAR
);

-- One row per game. Team columns are Yahoo-style tricodes (TOR, GSW, ...) so
-- this joins straight onto players.editorial_team_abbr with no lookup table.
CREATE TABLE IF NOT EXISTS nba_schedule (
    pull_id         BIGINT NOT NULL,
    season          VARCHAR NOT NULL,
    game_id         VARCHAR,
    game_date       DATE,
    home_team       VARCHAR,
    away_team       VARCHAR,
    game_label      VARCHAR,          -- NULL for a normal game; else e.g. 'Emirates NBA Cup'
    is_neutral_site BOOLEAN
);

CREATE OR REPLACE VIEW latest_nba_schedule_pull AS
SELECT season, max(pull_id) AS pull_id
FROM nba_schedule_pulls
WHERE status = 'success'
GROUP BY season;

CREATE OR REPLACE VIEW v_nba_schedule AS
SELECT s.* FROM nba_schedule s JOIN latest_nba_schedule_pull p USING (season, pull_id);

-- One row per (team, game) instead of per game — the join surface
-- projection.py needs to count real games per NBA team per week.
CREATE OR REPLACE VIEW v_nba_team_schedule AS
SELECT season, game_id, game_date, home_team AS nba_team, away_team AS opponent, true AS is_home, game_label
FROM v_nba_schedule
UNION ALL
SELECT season, game_id, game_date, away_team AS nba_team, home_team AS opponent, false AS is_home, game_label
FROM v_nba_schedule;

-- --- Composite rankings ---
--
-- The one ordering derived from several ranking sources at once. Derived, not
-- pulled: nothing here comes off the wire, so it is not a fourth pull sequence
-- but the same append-only shape — one `composite_runs` row per run, the rows
-- it produced stamped with its id, and a view resolving to the newest success
-- per kind. A run records the ranking pulls and the parameters it was computed
-- from, which is what makes an old ordering readable months later without
-- guessing what went into it. Recomputing appends; it never rewrites.

CREATE SEQUENCE IF NOT EXISTS composite_run_id_seq START 1;

CREATE TABLE IF NOT EXISTS composite_runs (
    run_id      BIGINT PRIMARY KEY,
    kind        VARCHAR NOT NULL,        -- registry Source.kind, e.g. 'dynasty'
    computed_at TIMESTAMP NOT NULL,
    status      VARCHAR NOT NULL,        -- running | success | error
    sources     VARCHAR,                 -- JSON {source: ranking_pull_id} folded in
    params      VARCHAR,                 -- JSON {curve, censor} the run used
    note        VARCHAR
);

-- One row per player per run, already in composite order. `votes` carries each
-- source's contribution rather than one column per source, so a source added to
-- the registry needs no migration here.
CREATE TABLE IF NOT EXISTS composite_rankings (
    run_id          BIGINT NOT NULL,
    rank            INTEGER NOT NULL,
    score           DOUBLE,
    player_name     VARCHAR,
    player_name_key VARCHAR,
    player_key      VARCHAR,
    team_abbr       VARCHAR,
    age             DOUBLE,
    n_sources       INTEGER,
    n_votes         INTEGER,
    consensus       DOUBLE,
    spread          INTEGER,
    votes           VARCHAR
);

CREATE OR REPLACE VIEW latest_composite_run AS
SELECT kind, max(run_id) AS run_id
FROM composite_runs
WHERE status = 'success'
GROUP BY kind;

CREATE OR REPLACE VIEW v_composite_rankings AS
SELECT c.* FROM composite_rankings c JOIN latest_composite_run r USING (run_id);

-- --- Documentation ---
--
-- The same facts as the comments above, in the catalogue instead of the file, so
-- that anything holding a connection — a `duckdb` shell, a notebook, an agent
-- reading duckdb_columns() — can find them without this file. Readable from a
-- read-only connection; `COMMENT ON` costs about a millisecond, so re-applying
-- the whole block on every init_schema is free.
--
-- This section must stay last: CREATE OR REPLACE VIEW drops the comments on the
-- view it replaces, so every comment has to be applied after its definition.
-- Comment what is not evident from the column name — a join key, a gotcha, an
-- enum's members — rather than restating the name in a sentence.

COMMENT ON MACRO name_key IS
    'Standardize a name for matching: lowercase, accents folded, punctuation '
    'and Jr./Sr./II-V dropped. Mirrors fantasy.names.normalize() minus its '
    'nickname table; keep the two in sync.';

-- League snapshot

COMMENT ON TABLE pulls IS
    'One row per league snapshot attempt, newest last. The parent of every '
    'league table below: each of them stamps the pull_id it was written by, and '
    'nothing is ever updated or deleted except this row''s own status.';
COMMENT ON COLUMN pulls.status IS
    'running | success | partial | error. Only success and partial reach the '
    'v_* views, which is what keeps a half-finished pull invisible.';
COMMENT ON COLUMN pulls.note IS 'Free text set when the pull closed: on a partial pull, which steps failed.';

COMMENT ON TABLE leagues IS 'League identity and dates, one row per pull.';
COMMENT ON COLUMN leagues.scoring_type IS
    'Yahoo''s code — head, headone, headpoint, roto. analysis/rules.py refuses '
    'anything but head-to-head category scoring.';
COMMENT ON COLUMN leagues.start_date IS 'ISO date as a string, straight from Yahoo.';
COMMENT ON COLUMN leagues.end_date IS 'ISO date as a string, straight from Yahoo.';

COMMENT ON TABLE league_settings IS
    'Settings the model would rather read than assume. Rows written before the '
    'current parser are mostly NULL; the parser now returns 0/False for a '
    'missing field, so a NULL here means old data, not a live failure (issue '
    '#4).';

COMMENT ON TABLE league_stat_categories IS
    'The categories this league scores. Nothing downstream hardcodes the nine '
    'standard ones — analysis/rules.py reads them from here.';
COMMENT ON COLUMN league_stat_categories.stat_id IS
    'Yahoo stat id, as a string. The join key everything should use; see the '
    'note on player_stats.stat_name.';
COMMENT ON COLUMN league_stat_categories.sort_order IS
    '1 when a higher value wins, 0 when lower wins (turnovers). Never branch on '
    'this directly — query.beats() is the one place that decides a category.';
COMMENT ON COLUMN league_stat_categories.is_only_display IS
    'True for a category Yahoo shows but does not score; excluded from the '
    'model.';

COMMENT ON TABLE league_roster_positions IS
    'Roster slots and how many of each. rules.is_bench() decides which of these '
    'are bench or IL rather than any caller testing the string.';

COMMENT ON TABLE teams IS 'The twelve managers, their records and standings, per pull.';
COMMENT ON COLUMN teams.team_key IS 'Yahoo key, <game>.l.<league>.t.<id>. Joins to rosters.team_key.';
COMMENT ON COLUMN teams.is_my_team IS 'True for exactly one row per pull — the authenticated user''s team.';

COMMENT ON TABLE players IS
    'Every player seen in the pull, rostered or free agent. Biographical only; '
    'the numbers are in player_stats.';
COMMENT ON COLUMN players.player_key IS 'Yahoo key, <game>.p.<id>. The join key to rosters and player_stats.';
COMMENT ON COLUMN players.full_name IS
    'Yahoo''s spelling, accents and all ("Nikola Jokić"). Outside sources spell '
    'it differently, so joins against them go through '
    'name_key()/names.normalize().';
COMMENT ON COLUMN players.editorial_team_abbr IS 'NBA tricode (TOR, GSW). Joins straight to nba_schedule''s team columns.';
COMMENT ON COLUMN players.positions IS 'Eligible positions, e.g. [''PG'', ''SG''].';
COMMENT ON COLUMN players.status IS
    'Yahoo''s availability flag — NULL when active, else INJ, O, GTD, NA, ... '
    'projection.py reads it to discount a player''s games.';
COMMENT ON COLUMN players.percent_owned IS 'Share of Yahoo leagues rostering the player, 0-100.';

COMMENT ON TABLE rosters IS
    'Who holds whom, one row per (player, pull). Free agents are in here too, '
    'with is_free_agent set and no team_key.';
COMMENT ON COLUMN rosters.selected_position IS
    'The slot the player occupied when pulled (PG, C, BN, IL). NULL for a free '
    'agent.';
COMMENT ON COLUMN rosters.is_free_agent IS
    'True for an unrostered player. The free-agent side may be truncated: `pull '
    '--fa-limit` caps how many are fetched, so a small count here means the '
    'waiver search saw a fraction of the real pool, not that the pool is small.';

COMMENT ON TABLE player_stats IS
    'Long format: one row per (player, period, stat), so a league changing its '
    'categories never needs a migration. PIVOT for a wide view.';
COMMENT ON COLUMN player_stats.stat_period IS
    'season | last_7 | last_14 | last_30. A pull taken after the season ends '
    'returns full-season figures for all four, which makes projection.py''s '
    'recency blend a no-op on that snapshot rather than a broken one.';
COMMENT ON COLUMN player_stats.stat_id IS 'Yahoo stat id. Key on this, never on stat_name.';
COMMENT ON COLUMN player_stats.stat_name IS
    'Yahoo''s label, and unreliable: pulls predating the stat-map fix have '
    'makes and attempts transposed (stat_id 10 stored as ''3PTA'' when it is '
    '3PTM). Present for reading, not for joining — query._names() repairs it.';
COMMENT ON COLUMN player_stats.value IS
    'Parsed number. NULL where Yahoo sent something non-numeric — raw_value '
    'keeps the original.';
COMMENT ON COLUMN player_stats.raw_value IS
    'Yahoo''s string, kept verbatim; ratios arrive as ''.452'' and counting '
    'stats as ''-'' when absent.';

-- Rankings

COMMENT ON TABLE ranking_pulls IS
    'One row per ranking-site scrape. A pull sequence of its own, separate from '
    '`pulls`, because rankings run on their own cadence and belong to no '
    'league.';
COMMENT ON COLUMN ranking_pulls.source IS
    'Registry key from sources/rankings/SOURCES, e.g. hashtag_dynasty, '
    'angle_dynasty.';
COMMENT ON COLUMN ranking_pulls.source_url IS
    'What was actually fetched. For a remembers_url source (angle_dynasty, '
    'whose Top 300 moves to a new post each edition) the newest successful row '
    'here is the default URL for the next pull.';
COMMENT ON COLUMN ranking_pulls.status IS 'running | success | error. Only success reaches v_player_rankings.';

COMMENT ON TABLE player_rankings IS
    'One row per (source, player) per pull — an outside opinion about a player, '
    'joined to the league by name.';
COMMENT ON COLUMN player_rankings.player_name IS 'The source''s own spelling, unmodified.';
COMMENT ON COLUMN player_rankings.player_name_key IS
    'names.normalize(player_name) — the exact string the match was attempted '
    'on, stored so a miss can be debugged in SQL without re-running the '
    'normalizer.';
COMMENT ON COLUMN player_rankings.player_key IS
    'The matched players.player_key, or NULL when nothing matched. An unmatched '
    'row is kept rather than dropped: it is evidence about normalize(), and '
    '`rankings show` prints these as unmatched.';
COMMENT ON COLUMN player_rankings.extra IS
    'Source-specific fields as a JSON object; read with ->>. Angle rows carry '
    'the sheet''s own title as ''edition'', so a stored ranking still says '
    'which edition it came from after the URL behind it has moved on.';

-- NBA schedule

COMMENT ON TABLE nba_schedule_pulls IS
    'One row per stats.nba.com schedule scrape. The third independent pull '
    'sequence, keyed by NBA season rather than by league.';
COMMENT ON COLUMN nba_schedule_pulls.season IS 'NBA season string, e.g. ''2026-27''.';
COMMENT ON COLUMN nba_schedule_pulls.status IS 'running | success | error. Only success reaches v_nba_schedule.';

COMMENT ON TABLE nba_schedule IS
    'One row per game. What projection.team_schedule fits per-team '
    'games-per-week from; without it the model falls back to a flat 3.5 and '
    'says so in `fantasy rules`.';
COMMENT ON COLUMN nba_schedule.home_team IS
    'Yahoo-style tricode, so this joins to players.editorial_team_abbr with no '
    'lookup table.';
COMMENT ON COLUMN nba_schedule.away_team IS
    'Yahoo-style tricode, so this joins to players.editorial_team_abbr with no '
    'lookup table.';
COMMENT ON COLUMN nba_schedule.game_label IS 'NULL for a normal game, else e.g. ''Emirates NBA Cup''.';

-- Views. Three families, each resolving to the newest successful pull of its own
-- kind, so a stale schedule and a fresh league snapshot coexist happily.

COMMENT ON VIEW latest_pull IS
    'The newest success-or-partial pull_id per league. What every v_* below '
    'joins against.';
COMMENT ON VIEW v_leagues IS 'leagues, current pull only.';
COMMENT ON VIEW v_league_settings IS
    'league_settings, current pull only. Mostly NULL on older pulls — see the '
    'table comment.';
COMMENT ON VIEW v_stat_categories IS
    'league_stat_categories, current pull only. The categories the model '
    'scores.';
COMMENT ON VIEW v_roster_positions IS 'league_roster_positions, current pull only.';
COMMENT ON VIEW v_teams IS 'teams, current pull only.';
COMMENT ON VIEW v_players IS
    'players, current pull only, plus full_name_key — name_key(full_name), the '
    'join column for anything coming from outside Yahoo.';
COMMENT ON VIEW v_rosters IS 'rosters, current pull only. Rostered players and free agents together.';
COMMENT ON VIEW v_player_stats IS 'player_stats, current pull only.';
COMMENT ON VIEW v_roster_players IS
    'Rostered players with their team and manager attached — free agents '
    'excluded. The usual starting point for a question about who holds whom.';
COMMENT ON VIEW v_my_team IS 'v_roster_players restricted to the authenticated user''s team.';
COMMENT ON VIEW v_free_agents IS
    'The unrostered side of v_rosters. Truncated by `pull --fa-limit` — see '
    'rosters.is_free_agent before reading anything into its size.';
COMMENT ON VIEW latest_ranking_pull IS 'The newest successful ranking_pull_id per source.';
COMMENT ON VIEW v_player_rankings IS
    'player_rankings from each source''s newest successful pull. Sources are '
    'independent: one going stale does not hold the others back.';
COMMENT ON VIEW latest_nba_schedule_pull IS 'The newest successful schedule pull_id per season.';
COMMENT ON VIEW v_nba_schedule IS 'nba_schedule, newest successful pull per season.';
COMMENT ON VIEW v_nba_team_schedule IS
    'v_nba_schedule unpivoted to one row per (team, game), which is the shape '
    'projection.py counts games per team per week from.';

COMMENT ON TABLE composite_runs IS
    'One row per `fantasy rankings composite build`. Derived rather than '
    'pulled, but kept on the same append-only footing: `sources` and `params` '
    'pin what an old ordering was computed from, so it stays readable after '
    'the rankings behind it have moved on.';
COMMENT ON COLUMN composite_runs.kind IS
    'What the sources rank on, from Source.kind in the sources/rankings '
    'registry. Only same-kind lists are averaged together.';
COMMENT ON COLUMN composite_runs.sources IS
    'JSON {source: ranking_pull_id} — which pull of each source went in. The '
    'link back to player_rankings for anything the ordering has to justify.';
COMMENT ON COLUMN composite_runs.params IS
    'JSON {curve, censor}. Stored because retuning either changes every score, '
    'and two runs are only comparable when these match.';
COMMENT ON COLUMN composite_runs.status IS 'running | success | error. Only success reaches v_composite_rankings.';

COMMENT ON TABLE composite_rankings IS
    'The reranked players of one run, already in composite order. '
    'League-agnostic like player_rankings — join player_name_key to '
    'v_players.full_name_key for who holds whom.';
COMMENT ON COLUMN composite_rankings.score IS
    'Mean of the sources'' votes, 0-100, where 100 is the value of a unanimous '
    '#1. Comparable only within a run: it moves with composite_runs.params.';
COMMENT ON COLUMN composite_rankings.consensus IS
    'Geometric mean of the ranks the player actually has, ignoring censored '
    'and inferred votes. A read of where the sources that saw him put him.';
COMMENT ON COLUMN composite_rankings.n_sources IS 'Sources that ranked him outright.';
COMMENT ON COLUMN composite_rankings.n_votes IS
    'Sources that voted at all — ranked, passed or inferred. Below n_sources '
    'means a list was too short to have an opinion, not that it was ignored.';
COMMENT ON COLUMN composite_rankings.spread IS
    'Widest disagreement in ranks among the sources that ranked him; NULL when '
    'only one did. Where outside information is worth most.';
COMMENT ON COLUMN composite_rankings.votes IS
    'JSON {source: {rank, effective, kind, value}}. `kind` is ranked (the '
    'source said so), passed (it saw him and left him off, scored at its list '
    'end) or inferred (it has an empty slot and this is a guess at who holds '
    'it) — see analysis/composite.py.';

COMMENT ON VIEW latest_composite_run IS 'The newest successful composite run_id per kind.';
COMMENT ON VIEW v_composite_rankings IS
    'composite_rankings from the newest successful run of each kind. What '
    '`fantasy rankings composite show` reads.';
