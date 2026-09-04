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
