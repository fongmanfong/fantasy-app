from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime

from ..database.connection import get_db
from ..database.models import League, SyncLog, AppSettings
from ..services.yahoo_service import YahooService
from ..services.news_service import NewsService
from ..scheduler import set_sync_interval, get_sync_interval_hours

router = APIRouter(prefix="/api/leagues", tags=["leagues"])


class AddLeagueRequest(BaseModel):
    yahoo_league_id: str


class SyncIntervalRequest(BaseModel):
    hours: float


@router.get("/")
def list_leagues(db: Session = Depends(get_db)):
    leagues = db.query(League).filter_by(is_active=True).all()
    return [
        {
            "id": l.id,
            "yahoo_league_id": l.yahoo_league_id,
            "name": l.name,
            "season": l.season,
            "num_teams": l.num_teams,
            "current_week": l.current_week,
            "scoring_type": l.scoring_type,
        }
        for l in leagues
    ]


@router.post("/")
def add_league(req: AddLeagueRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    svc = YahooService(db)
    try:
        league = svc.sync_league(req.yahoo_league_id)
        background_tasks.add_task(_background_full_sync, req.yahoo_league_id)
        return {
            "id": league.id,
            "yahoo_league_id": league.yahoo_league_id,
            "name": league.name,
            "message": "League added. Full sync running in background.",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{league_id}")
def remove_league(league_id: int, db: Session = Depends(get_db)):
    league = db.query(League).get(league_id)
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    league.is_active = False
    db.commit()
    return {"message": "League removed"}


@router.post("/{league_id}/sync")
def trigger_sync(league_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    league = db.query(League).get(league_id)
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    background_tasks.add_task(_background_full_sync, league.yahoo_league_id)
    return {"message": "Sync started in background"}


@router.post("/news/sync")
def trigger_news_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(_background_news_sync)
    return {"message": "News sync started in background"}


@router.get("/{league_id}/sync/status")
def sync_status(league_id: int, db: Session = Depends(get_db)):
    logs = (
        db.query(SyncLog)
        .filter_by(league_id=league_id)
        .order_by(SyncLog.started_at.desc())
        .limit(10)
        .all()
    )
    return [
        {
            "sync_type": l.sync_type,
            "status": l.status,
            "message": l.message,
            "started_at": l.started_at.isoformat() if l.started_at else None,
            "completed_at": l.completed_at.isoformat() if l.completed_at else None,
        }
        for l in logs
    ]


@router.get("/{league_id}/settings")
def get_settings(league_id: int, db: Session = Depends(get_db)):
    from ..database.models import LeagueSettings
    settings = db.query(LeagueSettings).filter_by(league_id=league_id).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")
    return {
        "stat_categories": settings.stat_categories,
        "stat_weights": settings.stat_weights,
        "roster_positions": settings.roster_positions,
        "playoff_start_week": settings.playoff_start_week,
        "waiver_type": settings.waiver_type,
    }


@router.get("/app/sync-interval")
def get_interval(db: Session = Depends(get_db)):
    return {"hours": get_sync_interval_hours()}


@router.post("/app/sync-interval")
def update_interval(req: SyncIntervalRequest):
    if req.hours < 0.5 or req.hours > 168:
        raise HTTPException(status_code=400, detail="Interval must be between 0.5 and 168 hours")
    set_sync_interval(req.hours)
    return {"hours": req.hours, "message": "Sync interval updated"}


def _background_full_sync(yahoo_league_id: str):
    from ..database.connection import db_session
    with db_session() as db:
        svc = YahooService(db)
        svc.full_sync(yahoo_league_id)


def _background_news_sync():
    from ..database.connection import db_session
    with db_session() as db:
        svc = NewsService(db)
        svc.scrape_all()
