"""
Player news scraper.
Scrapes NBA Fantasy news from multiple sources and stores in DB.
"""
import logging
import re
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from ..database.models import Player, PlayerNews

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


class NewsService:
    def __init__(self, db: Session):
        self.db = db

    def scrape_all(self):
        results = {"nbc": 0, "errors": []}
        try:
            results["nbc"] = self._scrape_nbc_sports()
        except Exception as e:
            logger.error(f"NBC Sports scrape failed: {e}")
            results["errors"].append(f"NBC Sports: {e}")

        return results

    def _scrape_nbc_sports(self) -> int:
        url = "https://www.nbcsports.com/fantasy/basketball"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to fetch NBC Sports: {e}")
            return 0

        soup = BeautifulSoup(resp.text, "html.parser")
        count = 0

        # NBC Sports fantasy page has player news items
        articles = soup.find_all("article") or soup.find_all(class_=re.compile("PlayerNews|player-news|news-item"))

        for article in articles[:50]:
            try:
                # Try to extract player name, headline, and body
                headline_el = (
                    article.find("h1") or article.find("h2") or
                    article.find("h3") or article.find(class_=re.compile("headline|title"))
                )
                body_el = (
                    article.find("p") or
                    article.find(class_=re.compile("analysis|body|content|description"))
                )

                headline = headline_el.get_text(strip=True) if headline_el else ""
                body = body_el.get_text(strip=True) if body_el else ""

                if not headline and not body:
                    continue

                # Try to match player name from headline
                player = self._find_player_by_text(headline + " " + body)

                published_at = self._extract_date(article)

                news = PlayerNews(
                    player_id=player.id if player else None,
                    source="NBC Sports",
                    headline=headline[:500] if headline else None,
                    body=body[:2000] if body else None,
                    published_at=published_at,
                    scraped_at=datetime.utcnow(),
                )
                self.db.add(news)
                count += 1
            except Exception as e:
                logger.debug(f"Failed to parse article: {e}")
                continue

        self.db.commit()
        return count

    def _find_player_by_text(self, text: str) -> Optional[Player]:
        """Try to match a player name from text against our player DB."""
        players = self.db.query(Player).all()
        text_lower = text.lower()
        for player in players:
            if player.name and player.name.lower() in text_lower:
                return player
        return None

    def _extract_date(self, element) -> Optional[datetime]:
        """Try to extract a published date from an article element."""
        time_el = element.find("time")
        if time_el:
            dt_str = time_el.get("datetime") or time_el.get_text(strip=True)
            try:
                return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            except Exception:
                pass
        return None

    def get_recent_news(self, player_id: Optional[int] = None, limit: int = 20) -> list:
        query = self.db.query(PlayerNews)
        if player_id:
            query = query.filter_by(player_id=player_id)
        return (
            query.order_by(PlayerNews.scraped_at.desc())
            .limit(limit)
            .all()
        )

    def get_news_for_players(self, player_ids: list[int], limit_per_player: int = 3) -> dict:
        """Returns {player_id: [news items]} for a list of player IDs."""
        result = {}
        for pid in player_ids:
            news = (
                self.db.query(PlayerNews)
                .filter_by(player_id=pid)
                .order_by(PlayerNews.scraped_at.desc())
                .limit(limit_per_player)
                .all()
            )
            result[pid] = [
                {
                    "headline": n.headline,
                    "body": n.body,
                    "source": n.source,
                    "published_at": n.published_at.isoformat() if n.published_at else None,
                }
                for n in news
            ]
        return result
