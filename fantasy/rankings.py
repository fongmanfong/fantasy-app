"""Fetches a ranking site, parses it, and appends the result to DuckDB.

Shaped like pull.py but decoupled from a league pull: rankings have their own pull
sequence (`ranking_pulls`) and aren't stamped with a league_key, because a ranking
pull happens on its own cadence and isn't specific to one Yahoo league.
"""
import json
import logging
import re
from dataclasses import dataclass

from .sources.rankings import SOURCES, fetch
from .store import db

logger = logging.getLogger(__name__)


@dataclass
class RankingPullResult:
    ranking_pull_id: int
    source: str
    source_url: str
    rows: int = 0
    matched: int = 0
    error: str | None = None

    @property
    def status(self) -> str:
        return "error" if self.error else "success"


_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")
_PUNCT = re.compile(r"[.'\-]")


def _normalize(name: str) -> str:
    """
    Loose match key for joining a scraped name against v_players.full_name.

    Sites and Yahoo don't always agree on punctuation or a "Jr." suffix; this closes
    that gap without attempting anything fuzzier (no edit distance), so a genuine
    mismatch — a nickname, a different transliteration — is left unmatched rather than
    silently paired with the wrong player.
    """
    name = _PUNCT.sub("", name.lower())
    name = _SUFFIX.sub("", name)
    return " ".join(name.split())


def _match_players(con) -> dict[str, str]:
    """normalized full_name -> player_key, from the latest league snapshot."""
    try:
        rows = con.execute("SELECT full_name, player_key FROM v_players").fetchall()
    except Exception:
        return {}  # no league snapshot yet — rankings still get stored, unmatched
    out: dict[str, str] = {}
    for full_name, player_key in rows:
        if full_name and player_key:
            out.setdefault(_normalize(full_name), player_key)
    return out


def run(source: str, url: str | None = None) -> RankingPullResult:
    if source not in SOURCES:
        known = ", ".join(sorted(SOURCES))
        raise RuntimeError(f"Unknown ranking source {source!r}. Known: {known}")

    src = SOURCES[source]
    source_url = url or src.url

    with db.connect() as con:
        db.init_schema(con)
        ranking_pull_id = db.new_ranking_pull(con, source, source_url)
        result = RankingPullResult(ranking_pull_id=ranking_pull_id, source=source, source_url=source_url)

        try:
            html = fetch.get(source_url)
            rows = src.parse(html)
        except Exception as exc:
            logger.warning("ranking pull %s failed: %s", source, exc)
            result.error = str(exc)
            db.complete_ranking_pull(con, ranking_pull_id, result.status, result.error)
            return result

        by_name = _match_players(con)

        payload = []
        for row in rows:
            player_key = by_name.get(_normalize(row["player_name"]))
            if player_key:
                result.matched += 1
            payload.append({
                "ranking_pull_id": ranking_pull_id,
                "source": source,
                "rank": row.get("rank"),
                "player_name": row.get("player_name"),
                "player_key": player_key,
                "team_abbr": row.get("team_abbr"),
                "positions": row.get("positions") or [],
                "age": row.get("age"),
                "extra": json.dumps(row.get("extra") or {}),
            })

        db.insert_ranking_rows(con, payload)
        result.rows = len(payload)

        note = f"{result.matched}/{result.rows} matched to the league snapshot" if result.rows else "no rows parsed"
        db.complete_ranking_pull(con, ranking_pull_id, result.status, note)

    return result
