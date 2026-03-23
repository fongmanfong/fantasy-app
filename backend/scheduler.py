"""
APScheduler-based background sync scheduler.
Reads sync cadence from app settings and keeps data fresh.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from .database.connection import db_session
from .database.models import League, AppSettings
from .services.yahoo_service import YahooService
from .services.news_service import NewsService

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")
_sync_job_id = "fantasy_sync"
_news_job_id = "news_sync"


def run_full_sync():
    logger.info("Scheduled sync starting...")
    with db_session() as db:
        yahoo = YahooService(db)
        leagues = db.query(League).filter_by(is_active=True).all()
        league_ids = [l.yahoo_league_id for l in leagues]

    for lid in league_ids:
        try:
            with db_session() as db:
                yahoo = YahooService(db)
                yahoo.full_sync(lid)
            logger.info(f"Synced league {lid}")
        except Exception as e:
            logger.error(f"Sync failed for league {lid}: {e}")


def run_news_sync():
    logger.info("News sync starting...")
    try:
        with db_session() as db:
            news = NewsService(db)
            result = news.scrape_all()
        logger.info(f"News sync complete: {result}")
    except Exception as e:
        logger.error(f"News sync failed: {e}")


def get_sync_interval_hours() -> float:
    with db_session() as db:
        setting = db.query(AppSettings).filter_by(key="sync_interval_hours").first()
        if setting and setting.value:
            try:
                return float(setting.value)
            except ValueError:
                pass
    return 6.0  # default: every 6 hours


def set_sync_interval(hours: float):
    with db_session() as db:
        setting = db.query(AppSettings).filter_by(key="sync_interval_hours").first()
        if not setting:
            setting = AppSettings(key="sync_interval_hours")
            db.add(setting)
        setting.value = str(hours)

    # Reschedule the job
    if scheduler.get_job(_sync_job_id):
        scheduler.reschedule_job(
            _sync_job_id,
            trigger=IntervalTrigger(hours=hours)
        )
        logger.info(f"Sync interval updated to {hours} hours")


def start_scheduler():
    if scheduler.running:
        return

    hours = get_sync_interval_hours()
    scheduler.add_job(
        run_full_sync,
        trigger=IntervalTrigger(hours=hours),
        id=_sync_job_id,
        replace_existing=True,
        name="Fantasy Data Sync",
    )
    scheduler.add_job(
        run_news_sync,
        trigger=IntervalTrigger(hours=3),
        id=_news_job_id,
        replace_existing=True,
        name="Player News Sync",
    )
    scheduler.start()
    logger.info(f"Scheduler started. Sync every {hours}h, news every 3h")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
