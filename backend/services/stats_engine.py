"""
Stats engine.
Computes player values, category contributions, and matchup projections
dynamically based on league settings.
"""
import logging
from typing import Optional

import pandas as pd
import numpy as np
from sqlalchemy.orm import Session

from ..database.models import (
    League, LeagueSettings, Team, Player, PlayerStats, Roster, Matchup
)

logger = logging.getLogger(__name__)


class StatsEngine:
    def __init__(self, db: Session):
        self.db = db

    def get_league_settings(self, league_id: int) -> LeagueSettings:
        return self.db.query(LeagueSettings).filter_by(league_id=league_id).first()

    def get_active_stat_names(self, league_id: int) -> list[str]:
        """Returns stat category names that are scored (not display-only)."""
        settings = self.get_league_settings(league_id)
        if not settings or not settings.stat_categories:
            return ["PTS", "REB", "AST", "ST", "BLK", "TO", "FG%", "FT%", "3PTM"]
        return [
            cat["name"]
            for cat in settings.stat_categories
            if not cat.get("is_only_display", False)
        ]

    def get_scoring_type(self, league_id: int) -> str:
        league = self.db.query(League).get(league_id)
        return league.scoring_type if league else "headhead_each_category"

    def player_stats_to_df(self, league_id: int, period: str = "last_14") -> pd.DataFrame:
        """Build a DataFrame of all rostered/FA players with their stats."""
        stats = (
            self.db.query(PlayerStats, Player)
            .join(Player, PlayerStats.player_id == Player.id)
            .filter(
                PlayerStats.league_id == league_id,
                PlayerStats.stat_period == period
            )
            .all()
        )

        rows = []
        for ps, p in stats:
            row = {
                "player_id": p.id,
                "yahoo_player_id": p.yahoo_player_id,
                "name": p.name,
                "nba_team": p.nba_team,
                "positions": p.positions,
                "injury_status": p.injury_status or "Healthy",
                "games_played": ps.games_played,
                "games_this_week": ps.games_this_week,
            }
            row.update(ps.stats or {})
            rows.append(row)

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows)

    def compute_player_values(self, league_id: int, period: str = "last_14") -> pd.DataFrame:
        """
        Compute a composite value score per player based on league settings.
        For category leagues: z-score each category, sum them (flip TO).
        For points leagues: use stat weights.
        """
        df = self.player_stats_to_df(league_id, period)
        if df.empty:
            return df

        active_stats = self.get_active_stat_names(league_id)
        scoring_type = self.get_scoring_type(league_id)
        settings = self.get_league_settings(league_id)

        # Only include stats that actually exist in the data
        available_stats = [s for s in active_stats if s in df.columns]
        if not available_stats:
            df["value_score"] = 0.0
            return df

        if "points" in scoring_type.lower():
            # Points league: weighted sum
            weights = settings.stat_weights or {}
            score = pd.Series(0.0, index=df.index)
            for stat in available_stats:
                w = float(weights.get(stat, 1.0))
                gp = df["games_played"].replace(0, np.nan)
                per_game = df[stat] / gp
                score += w * per_game.fillna(0)
            df["value_score"] = score
        else:
            # Category league: z-score approach
            score = pd.Series(0.0, index=df.index)
            gp = df["games_played"].replace(0, np.nan)

            for stat in available_stats:
                per_game = (df[stat] / gp).fillna(0)
                std = per_game.std()
                if std == 0 or std != std:  # NaN check
                    continue
                z = (per_game - per_game.mean()) / std
                # Turnovers: lower is better
                if stat in ("TO",):
                    z = -z
                score += z

            df["value_score"] = score

        # Games this week bonus (availability multiplier)
        if "games_this_week" in df.columns:
            df["weekly_score"] = df["value_score"] * df["games_this_week"].fillna(0).clip(lower=0)
        else:
            df["weekly_score"] = df["value_score"]

        return df.sort_values("value_score", ascending=False)

    def matchup_analysis(self, league_id: int) -> dict:
        """
        Analyze the current matchup: category-by-category breakdown,
        which categories we're winning/losing, and margin.
        """
        league = self.db.query(League).get(league_id)
        my_team = self.db.query(Team).filter_by(league_id=league_id, is_my_team=True).first()
        if not my_team:
            return {"error": "My team not found"}

        matchup = (
            self.db.query(Matchup)
            .filter_by(league_id=league_id, is_current=True)
            .first()
        )
        if not matchup:
            return {"error": "No current matchup found"}

        opponent_id = (
            matchup.away_team_id if matchup.home_team_id == my_team.id
            else matchup.home_team_id
        )
        opponent = self.db.query(Team).get(opponent_id)

        active_stats = self.get_active_stat_names(league_id)
        scoring_type = self.get_scoring_type(league_id)

        # Use stored matchup stats (set during sync from Yahoo live data)
        if matchup.home_team_id == my_team.id:
            my_stats = matchup.home_stats or {}
            opp_stats = matchup.away_stats or {}
        else:
            my_stats = matchup.away_stats or {}
            opp_stats = matchup.home_stats or {}

        result = {
            "week": league.current_week,
            "my_team": my_team.name,
            "opponent": opponent.name if opponent else "Unknown",
            "scoring_type": scoring_type,
            "categories": {},
            "summary": {},
        }

        if "points" in scoring_type.lower():
            my_total = sum(my_stats.values())
            opp_total = sum(opp_stats.values())
            result["summary"] = {
                "my_score": round(my_total, 2),
                "opp_score": round(opp_total, 2),
                "winning": my_total > opp_total,
                "margin": round(my_total - opp_total, 2),
            }
        else:
            winning_cats = losing_cats = tied_cats = 0
            for stat in active_stats:
                my_val = my_stats.get(stat, 0.0)
                opp_val = opp_stats.get(stat, 0.0)
                if stat == "TO":
                    my_winning = my_val < opp_val
                    opp_winning = opp_val < my_val
                else:
                    my_winning = my_val > opp_val
                    opp_winning = opp_val > my_val

                if my_winning:
                    status = "winning"
                    winning_cats += 1
                elif opp_winning:
                    status = "losing"
                    losing_cats += 1
                else:
                    status = "tied"
                    tied_cats += 1

                result["categories"][stat] = {
                    "my_value": round(my_val, 3),
                    "opp_value": round(opp_val, 3),
                    "status": status,
                    "diff": round(my_val - opp_val, 3),
                }

            result["summary"] = {
                "winning_cats": winning_cats,
                "losing_cats": losing_cats,
                "tied_cats": tied_cats,
                "winning": winning_cats > losing_cats,
            }

        return result

    def _aggregate_team_stats(self, team_id: int, league_id: int, period: str = "last_7") -> dict:
        roster = self.db.query(Roster).filter_by(team_id=team_id, is_free_agent=False).all()
        totals = {}

        for entry in roster:
            if entry.roster_position in ("BN", "IL", "IL+"):
                continue
            ps = (
                self.db.query(PlayerStats)
                .filter_by(
                    player_id=entry.player_id,
                    league_id=league_id,
                    stat_period=period,
                )
                .first()
            )
            if not ps or not ps.stats:
                continue
            gp = ps.games_played or 1
            for stat, val in ps.stats.items():
                per_game = float(val) / gp
                totals[stat] = totals.get(stat, 0.0) + per_game

        return totals

    def waiver_wire_recommendations(self, league_id: int, top_n: int = 10) -> list[dict]:
        """
        Identify best free agent pickups based on value score and this week's schedule.
        """
        df = self.compute_player_values(league_id, period="last_14")
        if df.empty:
            return []

        # Only free agents
        fa_team = self.db.query(Team).filter_by(league_id=league_id, yahoo_team_id="0").first()
        if not fa_team:
            return []

        fa_player_ids = {
            r.player_id for r in
            self.db.query(Roster).filter_by(team_id=fa_team.id, is_free_agent=True).all()
        }

        fa_df = df[df["player_id"].isin(fa_player_ids)].head(top_n)

        active_stats = self.get_active_stat_names(league_id)
        result = []
        for _, row in fa_df.iterrows():
            stat_line = {s: round(float(row[s]), 2) for s in active_stats if s in row and pd.notna(row[s])}
            result.append({
                "player_id": int(row["player_id"]),
                "name": row["name"],
                "nba_team": row.get("nba_team"),
                "positions": row.get("positions", []),
                "injury_status": row.get("injury_status", "Healthy"),
                "value_score": round(float(row["value_score"]), 3),
                "weekly_score": round(float(row.get("weekly_score", 0)), 3),
                "games_this_week": int(row.get("games_this_week", 0)),
                "games_played": int(row.get("games_played", 0)),
                "stats": stat_line,
            })

        return result

    def my_team_summary(self, league_id: int) -> dict:
        my_team = self.db.query(Team).filter_by(league_id=league_id, is_my_team=True).first()
        if not my_team:
            return {"error": "My team not found"}

        df = self.compute_player_values(league_id, period="last_14")
        roster = self.db.query(Roster).filter_by(team_id=my_team.id).all()

        active_stats = self.get_active_stat_names(league_id)
        players = []
        for entry in roster:
            p = entry.player
            player_row = df[df["player_id"] == p.id]
            value = float(player_row["value_score"].iloc[0]) if not player_row.empty else 0.0
            weekly = float(player_row["weekly_score"].iloc[0]) if not player_row.empty else 0.0
            stat_line = {}
            if not player_row.empty:
                row = player_row.iloc[0]
                stat_line = {s: round(float(row[s]), 2) for s in active_stats if s in row and pd.notna(row[s])}

            players.append({
                "player_id": p.id,
                "name": p.name,
                "nba_team": p.nba_team,
                "positions": p.positions,
                "roster_position": entry.roster_position,
                "injury_status": p.injury_status or "Healthy",
                "value_score": round(value, 3),
                "weekly_score": round(weekly, 3),
                "stats": stat_line,
            })

        players.sort(key=lambda x: x["value_score"], reverse=True)

        return {
            "team_name": my_team.name,
            "wins": my_team.wins,
            "losses": my_team.losses,
            "ties": my_team.ties,
            "standing": my_team.standing,
            "players": players,
        }
