"""
Yahoo Fantasy API service.
Handles OAuth 2.0 flow and all data extraction from Yahoo Fantasy Sports.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from requests_oauthlib import OAuth2Session
from sqlalchemy.orm import Session

from ..database.models import (
    League, LeagueSettings, Team, Player, PlayerStats,
    Roster, Matchup, YahooCredentials, SyncLog, AppSettings
)

logger = logging.getLogger(__name__)

YAHOO_AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
REDIRECT_URI = "https://localhost"

# Map Yahoo stat IDs to readable names
YAHOO_STAT_MAP = {
    "0": "GP", "1": "GS", "2": "MIN",
    "3": "FGM", "4": "FGA", "5": "FG%",
    "6": "FTM", "7": "FTA", "8": "FT%",
    "9": "3PTM", "10": "3PTA", "11": "3PT%",
    "12": "PTS", "13": "OREB", "14": "DREB",
    "15": "REB", "16": "AST", "17": "ST",
    "18": "BLK", "19": "TO", "20": "A/T",
    "22": "+/-", "23": "DD2", "24": "TD3",
}


class YahooService:
    def __init__(self, db: Session):
        self.db = db
        self._session: Optional[OAuth2Session] = None
        self._credentials: Optional[YahooCredentials] = None

    def get_credentials(self) -> Optional[YahooCredentials]:
        return self.db.query(YahooCredentials).first()

    def save_credentials(self, client_id: str, client_secret: str) -> YahooCredentials:
        creds = self.db.query(YahooCredentials).first()
        if creds:
            creds.client_id = client_id
            creds.client_secret = client_secret
            creds.access_token = None
            creds.refresh_token = None
            creds.token_expires_at = None
        else:
            creds = YahooCredentials(client_id=client_id, client_secret=client_secret)
            self.db.add(creds)
        self.db.commit()
        self.db.refresh(creds)
        return creds

    def get_auth_url(self) -> str:
        creds = self.get_credentials()
        if not creds:
            raise ValueError("No Yahoo credentials configured")
        oauth = OAuth2Session(creds.client_id, redirect_uri=REDIRECT_URI, scope=["openid"])
        auth_url, _ = oauth.authorization_url(YAHOO_AUTH_URL)
        return auth_url

    def handle_callback(self, code: str) -> bool:
        creds = self.get_credentials()
        if not creds:
            raise ValueError("No Yahoo credentials configured")

        oauth = OAuth2Session(creds.client_id, redirect_uri=REDIRECT_URI)
        token = oauth.fetch_token(
            YAHOO_TOKEN_URL,
            code=code,
            client_secret=creds.client_secret,
        )
        self._store_token(creds, token)
        return True

    def _store_token(self, creds: YahooCredentials, token: dict):
        creds.access_token = token.get("access_token")
        creds.refresh_token = token.get("refresh_token")
        expires_in = token.get("expires_in", 3600)
        creds.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        creds.updated_at = datetime.utcnow()
        self.db.commit()

    def _get_oauth_session(self) -> OAuth2Session:
        creds = self.get_credentials()
        if not creds or not creds.access_token:
            raise ValueError("Not authenticated with Yahoo. Please complete OAuth flow.")

        def token_updater(token):
            self._store_token(creds, token)

        token = {
            "access_token": creds.access_token,
            "refresh_token": creds.refresh_token,
            "token_type": "Bearer",
            "expires_at": creds.token_expires_at.timestamp() if creds.token_expires_at else 0,
        }

        return OAuth2Session(
            creds.client_id,
            token=token,
            auto_refresh_url=YAHOO_TOKEN_URL,
            auto_refresh_kwargs={"client_id": creds.client_id, "client_secret": creds.client_secret},
            token_updater=token_updater,
        )

    def _get(self, path: str, params: dict = None) -> dict:
        session = self._get_oauth_session()
        params = params or {}
        params["format"] = "json"
        url = f"{YAHOO_API_BASE}{path}"
        resp = session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # --- League ---

    def fetch_league_metadata(self, yahoo_league_id: str) -> dict:
        data = self._get(f"/league/nba.l.{yahoo_league_id}/settings")
        return data.get("fantasy_content", {})

    def sync_league(self, yahoo_league_id: str) -> League:
        log = self._start_sync(None, "full")
        try:
            content = self.fetch_league_metadata(yahoo_league_id)
            league_data = content.get("league", [{}])[0]
            settings_raw = content.get("league", [{}, {}])[1].get("settings", {})
            # Yahoo returns settings as a list [{}] not a dict
            if isinstance(settings_raw, list):
                settings_data = settings_raw[0] if settings_raw else {}
            else:
                settings_data = settings_raw

            league = self.db.query(League).filter_by(yahoo_league_id=yahoo_league_id).first()
            if not league:
                league = League(yahoo_league_id=yahoo_league_id)
                self.db.add(league)

            league.name = league_data.get("name", f"League {yahoo_league_id}")
            league.season = int(league_data.get("season", 0))
            league.num_teams = int(league_data.get("num_teams", 0))
            league.current_week = int(league_data.get("current_week", 0))
            league.scoring_type = league_data.get("scoring_type", "headhead_each_category")
            self.db.flush()

            self._sync_league_settings(league, settings_data)
            self.db.commit()
            self.db.refresh(league)

            self._complete_sync(log, "success")
            return league
        except Exception as e:
            self._complete_sync(log, "error", str(e))
            raise

    def _sync_league_settings(self, league: League, settings_data: dict):
        # stat_categories: Yahoo nests as {"stats": [{"stat": {...}}, ...]}
        stat_cats_container = settings_data.get("stat_categories", {})
        if isinstance(stat_cats_container, list):
            stat_cats_container = stat_cats_container[0] if stat_cats_container else {}
        stat_items = stat_cats_container.get("stats", [])
        if isinstance(stat_items, dict):
            stat_items = stat_items.get("stat", [])

        stat_categories = []
        for entry in stat_items:
            # Each entry is {"stat": {...}} or just {...}
            s = entry.get("stat", entry) if isinstance(entry, dict) else entry
            if not isinstance(s, dict):
                continue
            stat_id = str(s.get("stat_id", ""))
            is_display = s.get("is_only_display_stat", "0")
            stat_categories.append({
                "stat_id": stat_id,
                "name": YAHOO_STAT_MAP.get(stat_id, s.get("abbr", stat_id)),
                "display_name": s.get("display_name", s.get("name", stat_id)),
                "is_only_display": bool(int(is_display)) if is_display else False,
            })

        # roster_positions: Yahoo nests as [{"roster_position": {...}}, ...]
        roster_positions_raw = settings_data.get("roster_positions", [])
        if isinstance(roster_positions_raw, dict):
            roster_positions_raw = roster_positions_raw.get("roster_position", [])
        roster_positions = {}
        for entry in roster_positions_raw:
            # Each entry is {"roster_position": {...}} or just {...}
            rp = entry.get("roster_position", entry) if isinstance(entry, dict) else entry
            if not isinstance(rp, dict):
                continue
            pos = rp.get("position", "")
            count = int(rp.get("count", 1))
            roster_positions[pos] = count

        settings = self.db.query(LeagueSettings).filter_by(league_id=league.id).first()
        if not settings:
            settings = LeagueSettings(league_id=league.id)
            self.db.add(settings)

        settings.stat_categories = stat_categories
        settings.roster_positions = roster_positions
        settings.raw_settings = settings_data
        settings.playoff_start_week = int(settings_data.get("playoff_start_week", 0) or 0)

    # --- Yahoo response helpers ---

    def _parse_team_info(self, team_data: list) -> dict:
        """
        Parse Yahoo's team structure: [[ {team_key:...}, {team_id:...}, ...], {standings}, ...]
        Returns a flat dict of extracted fields.
        """
        result = {
            "yahoo_team_id": None, "name": None, "manager_name": None,
            "wins": 0, "losses": 0, "ties": 0, "standing": None,
        }
        if not team_data:
            return result

        # First element is a list of single-key dicts (with empty arrays mixed in)
        info_list = team_data[0] if isinstance(team_data[0], list) else [team_data[0]]
        for item in info_list:
            if not isinstance(item, dict):
                continue
            if "team_id" in item:
                result["yahoo_team_id"] = str(item["team_id"])
            if "name" in item:
                result["name"] = item["name"]
            if "managers" in item:
                mgrs = item["managers"]
                if isinstance(mgrs, list) and mgrs:
                    mgr = mgrs[0]
                    if isinstance(mgr, dict) and "manager" in mgr:
                        result["manager_name"] = mgr["manager"].get("nickname")
                    elif isinstance(mgr, dict):
                        result["manager_name"] = mgr.get("nickname")

        # Remaining elements may have standings, stats, etc.
        for elem in team_data[1:]:
            if not isinstance(elem, dict):
                continue
            if "team_standings" in elem:
                standings = elem["team_standings"]
                result["standing"] = standings.get("rank")
                outcome = standings.get("outcome_totals", {})
                result["wins"] = int(outcome.get("wins", 0))
                result["losses"] = int(outcome.get("losses", 0))
                result["ties"] = int(outcome.get("ties", 0))

        return result

    def _get_my_team_id(self, yahoo_league_id: str) -> str | None:
        """Use the users endpoint to find which team belongs to the logged-in user."""
        try:
            data = self._get(
                f"/users;use_login=1/games;game_keys=nba/leagues;league_keys=nba.l.{yahoo_league_id}/teams"
            )
            users = data.get("fantasy_content", {}).get("users", {}).get("0", {}).get("user", [{}, {}])
            games = users[1].get("games", {}).get("0", {}).get("game", [{}, {}])
            leagues = games[1].get("leagues", {}).get("0", {}).get("league", [{}, {}])
            teams = leagues[1].get("teams", {})
            for k, v in teams.items():
                if k == "count" or not isinstance(v, dict):
                    continue
                team_data = v.get("team", [[]])
                info = team_data[0] if isinstance(team_data[0], list) else [team_data[0]]
                for item in info:
                    if isinstance(item, dict) and "team_id" in item:
                        return str(item["team_id"])
        except Exception as e:
            logger.warning(f"Failed to determine my team: {e}")
        return None

    # --- Teams ---

    def sync_teams(self, league: League):
        log = self._start_sync(league.id, "roster")
        try:
            # Use standings endpoint for W/L data
            data = self._get(f"/league/nba.l.{league.yahoo_league_id}/standings")
            content = data.get("fantasy_content", {})
            standings_wrapper = content.get("league", [{}, {}])[1].get("standings", {})
            if isinstance(standings_wrapper, list):
                standings_wrapper = standings_wrapper[0] if standings_wrapper else {}
            teams_raw = standings_wrapper.get("teams", {})

            # Figure out my team
            my_team_id = self._get_my_team_id(league.yahoo_league_id)

            for key, val in teams_raw.items():
                if key == "count" or not isinstance(val, dict):
                    continue

                team_data = val.get("team", [])
                parsed = self._parse_team_info(team_data)

                yahoo_team_id = parsed["yahoo_team_id"]
                if not yahoo_team_id:
                    continue

                team = self.db.query(Team).filter_by(
                    league_id=league.id, yahoo_team_id=yahoo_team_id
                ).first()
                if not team:
                    team = Team(league_id=league.id, yahoo_team_id=yahoo_team_id)
                    self.db.add(team)

                team.name = parsed["name"] or f"Team {yahoo_team_id}"
                team.manager_name = parsed["manager_name"]
                team.is_my_team = (yahoo_team_id == my_team_id)
                team.wins = parsed["wins"]
                team.losses = parsed["losses"]
                team.ties = parsed["ties"]
                team.standing = parsed["standing"]
                team.updated_at = datetime.utcnow()

            self.db.commit()
            self._complete_sync(log, "success")
        except Exception as e:
            self._complete_sync(log, "error", str(e))
            raise

    # --- Roster ---

    def sync_rosters(self, league: League):
        teams = self.db.query(Team).filter_by(league_id=league.id).filter(Team.yahoo_team_id != "0").all()
        # Also clear free agents and re-fetch
        self.db.query(Roster).filter(
            Roster.team_id.in_([t.id for t in teams])
        ).delete(synchronize_session=False)
        self.db.commit()

        for team in teams:
            try:
                data = self._get(
                    f"/team/nba.l.{league.yahoo_league_id}.t.{team.yahoo_team_id}/roster/players"
                )
                content = data.get("fantasy_content", {})
                roster_data = (
                    content.get("team", [{}, {}])[1]
                    .get("roster", {})
                    .get("0", {})
                    .get("players", {})
                )
                self._process_roster(team, roster_data, is_free_agent=False)
            except Exception as e:
                logger.warning(f"Failed to sync roster for team {team.name}: {e}")

        self.db.commit()

    def sync_free_agents(self, league: League, count: int = 50):
        data = self._get(
            f"/league/nba.l.{league.yahoo_league_id}/players;status=FA;count={count}"
        )
        content = data.get("fantasy_content", {})
        players_raw = content.get("league", [{}, {}])[1].get("players", {})

        # Find or create a "free agents" pseudo-team
        fa_team = self.db.query(Team).filter_by(
            league_id=league.id, yahoo_team_id="0"
        ).first()
        if not fa_team:
            fa_team = Team(
                league_id=league.id,
                yahoo_team_id="0",
                name="Free Agents",
                is_my_team=False,
            )
            self.db.add(fa_team)
            self.db.flush()

        # Clear existing FA roster
        self.db.query(Roster).filter_by(team_id=fa_team.id).delete()

        self._process_roster(fa_team, players_raw, is_free_agent=True)
        self.db.commit()

    def _process_roster(self, team: Team, players_raw: dict, is_free_agent: bool):
        for key, val in players_raw.items():
            if key == "count" or not isinstance(val, dict):
                continue

            player_data = val.get("player", [])
            if not player_data:
                continue

            # player_data[0] is a list of single-key dicts (player info)
            # player_data[1+] may have selected_position, stats, etc.
            info_list = player_data[0] if isinstance(player_data[0], list) else [player_data[0]]

            yahoo_player_id = None
            player_name = None
            nba_team = None
            positions = []
            injury_status = "Healthy"
            roster_position = None

            for item in info_list:
                if not isinstance(item, dict):
                    continue
                if "player_id" in item:
                    yahoo_player_id = str(item["player_id"])
                if "name" in item and isinstance(item["name"], dict):
                    player_name = item["name"].get("full")
                if "editorial_team_abbr" in item:
                    nba_team = item["editorial_team_abbr"]
                if "display_position" in item:
                    positions = [p.strip() for p in item["display_position"].split(",")]
                if "eligible_positions" in item:
                    ep = item["eligible_positions"]
                    if isinstance(ep, list):
                        positions = [
                            p.get("position") if isinstance(p, dict) else p
                            for p in ep if (isinstance(p, dict) and p.get("position")) or isinstance(p, str)
                        ]
                if "status" in item:
                    injury_status = item["status"] or "Healthy"

            # selected_position is in a subsequent element
            for elem in player_data[1:]:
                if not isinstance(elem, dict):
                    continue
                if "selected_position" in elem:
                    sp = elem["selected_position"]
                    if isinstance(sp, list):
                        for sp_item in sp:
                            if isinstance(sp_item, dict) and "position" in sp_item:
                                roster_position = sp_item["position"]
                                break
                    elif isinstance(sp, dict):
                        roster_position = sp.get("position")

            if not yahoo_player_id:
                continue

            player = self.db.query(Player).filter_by(yahoo_player_id=yahoo_player_id).first()
            if not player:
                player = Player(
                    yahoo_player_id=yahoo_player_id,
                    name=player_name or f"Player {yahoo_player_id}",
                )
                self.db.add(player)
                self.db.flush()

            player.name = player_name or player.name or f"Player {yahoo_player_id}"
            player.nba_team = nba_team
            player.positions = positions
            player.injury_status = injury_status
            player.updated_at = datetime.utcnow()

            existing_roster = self.db.query(Roster).filter_by(
                team_id=team.id, player_id=player.id
            ).first()
            if not existing_roster:
                roster_entry = Roster(
                    team_id=team.id,
                    player_id=player.id,
                    roster_position=roster_position,
                    is_free_agent=is_free_agent,
                )
                self.db.add(roster_entry)
            else:
                existing_roster.roster_position = roster_position
                existing_roster.is_free_agent = is_free_agent

    # --- Stats ---

    def sync_player_stats(self, league: League):
        log = self._start_sync(league.id, "stats")
        try:
            periods = [
                ("season", "season"),
                ("last_7", "lastweek"),
                ("last_14", "last14days"),
                ("last_30", "lastmonth"),
            ]
            for period_key, yahoo_period in periods:
                self._sync_stats_for_period(league, period_key, yahoo_period)
            self._complete_sync(log, "success")
        except Exception as e:
            self._complete_sync(log, "error", str(e))
            raise

    def _sync_stats_for_period(self, league: League, period_key: str, yahoo_period: str):
        """Fetch stats for all rostered players in batches."""
        rostered_player_ids = []
        teams = self.db.query(Team).filter_by(league_id=league.id).all()
        for team in teams:
            for roster_entry in team.roster:
                rostered_player_ids.append(roster_entry.player.yahoo_player_id)

        if not rostered_player_ids:
            return

        # Process in batches of 25 (Yahoo API limit)
        for i in range(0, len(rostered_player_ids), 25):
            batch = rostered_player_ids[i:i+25]
            player_keys = ",".join(f"nba.p.{pid}" for pid in batch)
            try:
                data = self._get(
                    f"/players;player_keys={player_keys};out=stats;type={yahoo_period}"
                )
                content = data.get("fantasy_content", {})
                players_raw = content.get("players", {})
                self._process_stats_batch(players_raw, league.id, period_key)
            except Exception as e:
                logger.warning(f"Stats batch failed for period {period_key}: {e}")
                continue

        self.db.commit()

    def _process_stats_batch(self, players_raw: dict, league_id: int, period_key: str):
        for key, val in players_raw.items():
            if key == "count" or not isinstance(val, dict):
                continue

            player_data = val.get("player", [])
            if not player_data:
                continue

            info_list = player_data[0] if isinstance(player_data[0], list) else [player_data[0]]

            yahoo_player_id = None
            for item in info_list:
                if isinstance(item, dict) and "player_id" in item:
                    yahoo_player_id = str(item["player_id"])

            if not yahoo_player_id:
                continue

            player = self.db.query(Player).filter_by(yahoo_player_id=yahoo_player_id).first()
            if not player:
                continue

            stats_raw = {}
            gp = 0
            for elem in player_data[1:]:
                if not isinstance(elem, dict):
                    continue
                ps = elem.get("player_stats", {})
                if not ps:
                    continue
                # games_played may be missing or nested differently
                stats_list = ps.get("stats", [])
                if isinstance(stats_list, dict):
                    stats_list = stats_list.get("stat", [])
                for stat_entry in stats_list:
                    s = stat_entry.get("stat", stat_entry) if isinstance(stat_entry, dict) else stat_entry
                    if not isinstance(s, dict):
                        continue
                    stat_id = str(s.get("stat_id", ""))
                    name = YAHOO_STAT_MAP.get(stat_id, stat_id)
                    try:
                        stats_raw[name] = float(s.get("value", 0) or 0)
                    except (ValueError, TypeError):
                        stats_raw[name] = 0.0

            existing = self.db.query(PlayerStats).filter_by(
                player_id=player.id,
                league_id=league_id,
                stat_period=period_key,
            ).first()

            if not existing:
                existing = PlayerStats(
                    player_id=player.id,
                    league_id=league_id,
                    stat_period=period_key,
                )
                self.db.add(existing)

            existing.games_played = gp
            existing.stats = stats_raw
            existing.updated_at = datetime.utcnow()

    # --- Matchup ---

    def sync_current_matchup(self, league: League):
        log = self._start_sync(league.id, "matchup")
        try:
            my_team = self.db.query(Team).filter_by(league_id=league.id, is_my_team=True).first()
            if not my_team:
                self._complete_sync(log, "error", "No team marked as mine")
                return

            week = league.current_week
            data = self._get(
                f"/team/nba.l.{league.yahoo_league_id}.t.{my_team.yahoo_team_id}/matchups"
            )
            content = data.get("fantasy_content", {})
            matchups_raw = content.get("team", [{}, {}])[1].get("matchups", {})

            for key, val in matchups_raw.items():
                if key == "count" or not isinstance(val, dict):
                    continue
                matchup_data = val.get("matchup", {})
                if int(matchup_data.get("week", 0)) != week:
                    continue

                # Teams are under matchup["0"]["teams"]["0"] and ["1"]
                teams_container = matchup_data.get("0", {}).get("teams", {})
                # stat_winners tells us who's winning each category
                stat_winners = matchup_data.get("stat_winners", [])

                home_team_id = away_team_id = None
                home_stats = {}
                away_stats = {}
                category_results = {}

                for tkey, tval in teams_container.items():
                    if tkey == "count" or not isinstance(tval, dict):
                        continue

                    team_data = tval.get("team", [])
                    parsed = self._parse_team_info(team_data)
                    yahoo_tid = parsed["yahoo_team_id"]
                    if not yahoo_tid:
                        continue

                    db_team = self.db.query(Team).filter_by(
                        league_id=league.id, yahoo_team_id=yahoo_tid
                    ).first()
                    if not db_team:
                        continue

                    # Parse stats from second element of team_data
                    stats = {}
                    for elem in team_data[1:]:
                        if not isinstance(elem, dict):
                            continue
                        ts = elem.get("team_stats", {})
                        if not ts:
                            continue
                        for stat_entry in ts.get("stats", []):
                            s = stat_entry.get("stat", stat_entry) if isinstance(stat_entry, dict) else {}
                            stat_id = str(s.get("stat_id", ""))
                            name = YAHOO_STAT_MAP.get(stat_id, stat_id)
                            try:
                                stats[name] = float(s.get("value", 0) or 0)
                            except (ValueError, TypeError):
                                stats[name] = 0.0

                    if home_team_id is None:
                        home_team_id = db_team.id
                        home_stats = stats
                    else:
                        away_team_id = db_team.id
                        away_stats = stats

                # Build category results from stat_winners
                my_team_key = f"466.l.{league.yahoo_league_id}.t.{my_team.yahoo_team_id}"
                for sw_entry in stat_winners:
                    sw = sw_entry.get("stat_winner", sw_entry) if isinstance(sw_entry, dict) else {}
                    stat_id = str(sw.get("stat_id", ""))
                    winner_key = sw.get("winner_team_key", "")
                    name = YAHOO_STAT_MAP.get(stat_id, stat_id)
                    if winner_key == my_team_key:
                        category_results[name] = "home" if home_team_id and self.db.query(Team).get(home_team_id).is_my_team else "away"
                    elif winner_key:
                        category_results[name] = "away" if home_team_id and self.db.query(Team).get(home_team_id).is_my_team else "home"

                # Clear and re-save this week's matchup
                self.db.query(Matchup).filter_by(league_id=league.id, week=week).delete()

                matchup = Matchup(
                    league_id=league.id,
                    week=week,
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                    home_stats=home_stats,
                    away_stats=away_stats,
                    category_results=category_results,
                    is_current=True,
                )
                self.db.add(matchup)
                break  # only need current week

            self.db.commit()
            self._complete_sync(log, "success")
        except Exception as e:
            self._complete_sync(log, "error", str(e))
            raise

    # --- Full Sync ---

    def full_sync(self, yahoo_league_id: str):
        league = self.sync_league(yahoo_league_id)
        self.sync_teams(league)
        self.sync_rosters(league)
        for step_name, step_fn in [
            ("free_agents", lambda: self.sync_free_agents(league)),
            ("player_stats", lambda: self.sync_player_stats(league)),
            ("matchup", lambda: self.sync_current_matchup(league)),
        ]:
            try:
                step_fn()
            except Exception as e:
                logger.warning(f"Full sync step '{step_name}' failed: {e}")
        return league

    # --- Sync Log Helpers ---

    def _start_sync(self, league_id: Optional[int], sync_type: str) -> SyncLog:
        log = SyncLog(
            league_id=league_id,
            sync_type=sync_type,
            status="running",
            started_at=datetime.utcnow(),
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def _complete_sync(self, log: SyncLog, status: str, message: str = None):
        log.status = status
        log.message = message
        log.completed_at = datetime.utcnow()
        self.db.commit()
