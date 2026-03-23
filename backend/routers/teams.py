from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database.connection import get_db
from ..database.models import Team, Roster, Player, PlayerStats
from ..services.stats_engine import StatsEngine

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("/league/{league_id}")
def get_teams(league_id: int, db: Session = Depends(get_db)):
    teams = (
        db.query(Team)
        .filter_by(league_id=league_id)
        .filter(Team.yahoo_team_id != "0")
        .order_by(Team.standing)
        .all()
    )
    return [
        {
            "id": t.id,
            "yahoo_team_id": t.yahoo_team_id,
            "name": t.name,
            "manager_name": t.manager_name,
            "is_my_team": t.is_my_team,
            "wins": t.wins,
            "losses": t.losses,
            "ties": t.ties,
            "standing": t.standing,
        }
        for t in teams
    ]


@router.get("/my-team/{league_id}")
def get_my_team(
    league_id: int,
    stat_period: str = Query("last_14", pattern="^(season|last_7|last_14|last_30)$"),
    db: Session = Depends(get_db),
):
    engine = StatsEngine(db)
    summary = engine.my_team_summary(league_id)
    if "error" in summary:
        raise HTTPException(status_code=404, detail=summary["error"])
    return summary


@router.get("/{team_id}/roster")
def get_roster(
    team_id: int,
    league_id: int = Query(...),
    stat_period: str = Query("last_14"),
    db: Session = Depends(get_db),
):
    team = db.query(Team).get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    engine = StatsEngine(db)
    active_stats = engine.get_active_stat_names(league_id)

    players = []
    for entry in team.roster:
        if entry.is_free_agent:
            continue
        p = entry.player
        ps = (
            db.query(PlayerStats)
            .filter_by(player_id=p.id, league_id=league_id, stat_period=stat_period)
            .first()
        )
        stat_line = {}
        if ps and ps.stats:
            stat_line = {s: round(float(ps.stats.get(s, 0)), 2) for s in active_stats if s in ps.stats}

        players.append({
            "player_id": p.id,
            "yahoo_player_id": p.yahoo_player_id,
            "name": p.name,
            "nba_team": p.nba_team,
            "positions": p.positions,
            "roster_position": entry.roster_position,
            "injury_status": p.injury_status or "Healthy",
            "stats": stat_line,
        })

    return {"team": team.name, "players": players}


@router.get("/free-agents/{league_id}")
def get_free_agents(
    league_id: int,
    top_n: int = Query(25, le=50),
    db: Session = Depends(get_db),
):
    engine = StatsEngine(db)
    fas = engine.waiver_wire_recommendations(league_id, top_n=top_n)
    return {"free_agents": fas, "count": len(fas)}


@router.get("/matchup/{league_id}")
def get_current_matchup(league_id: int, db: Session = Depends(get_db)):
    engine = StatsEngine(db)
    result = engine.matchup_analysis(league_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
