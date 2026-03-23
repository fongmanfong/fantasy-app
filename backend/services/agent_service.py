"""
Claude AI agent service.
Uses Claude with tool use to analyze fantasy data and generate recommendations.
All analysis is contextualized to the specific league's scoring format.
"""
import json
import logging
import os
from typing import Any, Optional

import anthropic
from sqlalchemy.orm import Session

from ..database.models import League, LeagueSettings, Team, Player, PlayerStats, Matchup
from .stats_engine import StatsEngine
from .news_service import NewsService

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


TOOLS = [
    {
        "name": "get_league_context",
        "description": "Get the league settings, scoring type, stat categories, and roster configuration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "league_id": {"type": "integer", "description": "The league database ID"}
            },
            "required": ["league_id"]
        }
    },
    {
        "name": "get_my_team",
        "description": "Get my current roster with player stats, injury status, and value scores.",
        "input_schema": {
            "type": "object",
            "properties": {
                "league_id": {"type": "integer"},
                "stat_period": {"type": "string", "enum": ["season", "last_7", "last_14", "last_30"], "default": "last_14"}
            },
            "required": ["league_id"]
        }
    },
    {
        "name": "get_matchup",
        "description": "Get the current week's matchup analysis: category breakdown, winning/losing categories, projected outcome.",
        "input_schema": {
            "type": "object",
            "properties": {
                "league_id": {"type": "integer"}
            },
            "required": ["league_id"]
        }
    },
    {
        "name": "get_free_agents",
        "description": "Get top available free agents ranked by value, with stats and schedule information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "league_id": {"type": "integer"},
                "top_n": {"type": "integer", "default": 15}
            },
            "required": ["league_id"]
        }
    },
    {
        "name": "get_player_news",
        "description": "Get recent news, injury reports, and updates for a specific player or all players on my team.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {"type": "string", "description": "Player name to search for (optional)"},
                "league_id": {"type": "integer", "description": "If provided, get news for all players on my team"}
            }
        }
    },
    {
        "name": "get_league_standings",
        "description": "Get league standings and info about all teams.",
        "input_schema": {
            "type": "object",
            "properties": {
                "league_id": {"type": "integer"}
            },
            "required": ["league_id"]
        }
    },
    {
        "name": "compare_players",
        "description": "Compare two or more players by their stats in the context of this league's scoring.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of player names to compare"
                },
                "league_id": {"type": "integer"},
                "stat_period": {"type": "string", "enum": ["season", "last_7", "last_14", "last_30"], "default": "last_14"}
            },
            "required": ["player_names", "league_id"]
        }
    }
]


class AgentService:
    def __init__(self, db: Session):
        self.db = db
        self.stats_engine = StatsEngine(db)
        self.news_service = NewsService(db)
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self.client = anthropic.Anthropic(api_key=api_key)

    def _get_league_context(self, league_id: int) -> dict:
        league = self.db.query(League).get(league_id)
        settings = self.db.query(LeagueSettings).filter_by(league_id=league_id).first()
        if not league:
            return {"error": "League not found"}
        return {
            "league_id": league_id,
            "name": league.name,
            "season": league.season,
            "current_week": league.current_week,
            "scoring_type": league.scoring_type,
            "num_teams": league.num_teams,
            "stat_categories": settings.stat_categories if settings else [],
            "stat_weights": settings.stat_weights if settings else {},
            "roster_positions": settings.roster_positions if settings else {},
            "playoff_start_week": settings.playoff_start_week if settings else None,
        }

    def _get_my_team(self, league_id: int, stat_period: str = "last_14") -> dict:
        return self.stats_engine.my_team_summary(league_id)

    def _get_matchup(self, league_id: int) -> dict:
        return self.stats_engine.matchup_analysis(league_id)

    def _get_free_agents(self, league_id: int, top_n: int = 15) -> dict:
        fas = self.stats_engine.waiver_wire_recommendations(league_id, top_n=top_n)
        return {"free_agents": fas, "count": len(fas)}

    def _get_player_news(self, player_name: Optional[str] = None, league_id: Optional[int] = None) -> dict:
        if player_name:
            player = (
                self.db.query(Player)
                .filter(Player.name.ilike(f"%{player_name}%"))
                .first()
            )
            if not player:
                return {"error": f"Player '{player_name}' not found in database"}
            news = self.news_service.get_recent_news(player_id=player.id, limit=5)
            return {
                "player": player.name,
                "injury_status": player.injury_status,
                "news": [
                    {
                        "headline": n.headline,
                        "body": n.body,
                        "source": n.source,
                        "published_at": n.published_at.isoformat() if n.published_at else None,
                    }
                    for n in news
                ]
            }
        elif league_id:
            my_team = self.db.query(Team).filter_by(league_id=league_id, is_my_team=True).first()
            if not my_team:
                return {"error": "Team not found"}
            player_ids = [r.player_id for r in my_team.roster]
            news_by_player = self.news_service.get_news_for_players(player_ids)
            result = {}
            for r in my_team.roster:
                player = r.player
                result[player.name] = {
                    "injury_status": player.injury_status or "Healthy",
                    "news": news_by_player.get(player.id, [])
                }
            return result
        return {"error": "Provide player_name or league_id"}

    def _get_league_standings(self, league_id: int) -> dict:
        teams = (
            self.db.query(Team)
            .filter_by(league_id=league_id)
            .filter(Team.yahoo_team_id != "0")
            .order_by(Team.standing)
            .all()
        )
        return {
            "teams": [
                {
                    "name": t.name,
                    "manager": t.manager_name,
                    "wins": t.wins,
                    "losses": t.losses,
                    "ties": t.ties,
                    "standing": t.standing,
                    "is_my_team": t.is_my_team,
                }
                for t in teams
            ]
        }

    def _compare_players(self, player_names: list[str], league_id: int, stat_period: str = "last_14") -> dict:
        active_stats = self.stats_engine.get_active_stat_names(league_id)
        result = {}

        for name in player_names:
            player = (
                self.db.query(Player)
                .filter(Player.name.ilike(f"%{name}%"))
                .first()
            )
            if not player:
                result[name] = {"error": "Not found"}
                continue

            ps = (
                self.db.query(PlayerStats)
                .filter_by(player_id=player.id, league_id=league_id, stat_period=stat_period)
                .first()
            )

            df = self.stats_engine.compute_player_values(league_id, period=stat_period)
            player_row = df[df["player_id"] == player.id]
            value = float(player_row["value_score"].iloc[0]) if not player_row.empty else 0.0

            stat_line = {}
            if ps and ps.stats:
                stat_line = {s: round(float(ps.stats.get(s, 0)), 2) for s in active_stats}

            result[player.name] = {
                "nba_team": player.nba_team,
                "positions": player.positions,
                "injury_status": player.injury_status or "Healthy",
                "value_score": round(value, 3),
                "games_played": ps.games_played if ps else 0,
                "stats": stat_line,
            }

        return result

    def _dispatch_tool(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name == "get_league_context":
            return self._get_league_context(**tool_input)
        elif tool_name == "get_my_team":
            return self._get_my_team(**tool_input)
        elif tool_name == "get_matchup":
            return self._get_matchup(**tool_input)
        elif tool_name == "get_free_agents":
            return self._get_free_agents(**tool_input)
        elif tool_name == "get_player_news":
            return self._get_player_news(**tool_input)
        elif tool_name == "get_league_standings":
            return self._get_league_standings(**tool_input)
        elif tool_name == "compare_players":
            return self._compare_players(**tool_input)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    def chat(self, messages: list[dict], league_id: int) -> str:
        """
        Run a multi-turn agentic conversation.
        messages: list of {"role": "user"|"assistant", "content": str}
        """
        league = self.db.query(League).get(league_id)
        if not league:
            return "League not found. Please select a valid league."

        settings = self.db.query(LeagueSettings).filter_by(league_id=league_id).first()
        stat_cats = [c["name"] for c in (settings.stat_categories or []) if not c.get("is_only_display")] if settings else []

        system_prompt = f"""You are an expert NBA Fantasy Basketball analyst and strategist.

You are analyzing league: **{league.name}** (Season {league.season}, Week {league.current_week})
- Scoring type: {league.scoring_type}
- Stat categories: {', '.join(stat_cats) if stat_cats else 'Standard 9-cat'}
- League size: {league.num_teams} teams

Your job is to help the user make optimal fantasy decisions. You have access to tools to query live league data including rosters, stats, matchup info, free agents, and player news.

Guidelines:
- Always contextualize advice to THIS league's specific scoring format
- "No move" is a valid recommendation — explain why when appropriate
- For trade analysis, consider both short-term and long-term implications
- Be specific: name players, cite stats, explain reasoning
- Consider injury risk, schedule (games this week), and trends
- For category leagues, prioritize categories where the user is weakest
- For points leagues, prioritize total point production

When making recommendations, use the tools to gather current data before responding.
"""

        api_messages = list(messages)

        # Agentic loop
        while True:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=system_prompt,
                tools=TOOLS,
                messages=api_messages,
            )

            if response.stop_reason == "end_turn":
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                return "\n".join(text_parts)

            if response.stop_reason == "tool_use":
                # Add assistant message with tool use
                api_messages.append({"role": "assistant", "content": response.content})

                # Process all tool calls
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        try:
                            result = self._dispatch_tool(block.name, block.input)
                        except Exception as e:
                            result = {"error": str(e)}

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })

                api_messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason
            break

        return "I encountered an issue generating a response. Please try again."

    def generate_recommendations(self, league_id: int) -> str:
        """
        Proactively generate a comprehensive set of recommendations
        without any prior user message.
        """
        initial_message = {
            "role": "user",
            "content": (
                f"Please analyze my current team in league {league_id} and provide "
                "comprehensive recommendations. Include: "
                "1) Current matchup outlook and category analysis, "
                "2) Any players I should add or drop from the waiver wire, "
                "3) Start/sit considerations for this week, "
                "4) Any trade opportunities worth exploring, "
                "5) Overall assessment — if no moves are needed, say so clearly."
            )
        }
        return self.chat([initial_message], league_id)
