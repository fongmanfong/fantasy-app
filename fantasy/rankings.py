"""Fetches a ranking site, parses it, and appends the result to DuckDB.

Shaped like pull.py but decoupled from a league pull: rankings have their own pull
sequence (`ranking_pulls`) and aren't stamped with a league_key, because a ranking
pull happens on its own cadence and isn't specific to one Yahoo league.
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from . import query
from .names import normalize
from .sources.rankings import SOURCES, fetch
from .store import db

logger = logging.getLogger(__name__)


@dataclass
class RankingPullResult:
    """What one ranking-site pull scraped, and how much of it found a player."""
    ranking_pull_id: int
    source: str
    source_url: str
    fetched_url: str | None = None   # differs from source_url when the source resolves
    rows: int = 0
    matched: int = 0        # rows joined to a player_key in the league snapshot
    error: str | None = None
    remembered: bool = False         # later pulls will default to this source_url

    @property
    def status(self) -> str:
        """What gets written to the pull row: a failed scrape is still a pull."""
        return "error" if self.error else "success"


def run(source: str, url: str | None = None, file: str | None = None) -> RankingPullResult:
    """
    Scrape one ranking site and append it, matching rows to the league snapshot.

    `source` is a key of `sources.rankings.SOURCES`; `url` overrides that
    source's default page. Opens a **writable** connection, so it cannot run
    alongside another `fantasy` command.

    A source whose rankings move — angle publishes each edition as a new post
    pointing at a new Google Sheet — is marked `remembers_url`, and for those the
    URL of the last successful pull wins over the registry default, so `--url`
    only has to be given the once. A source may also `resolve` that URL into the
    one actually fetched (the sheet behind the article); `source_url` on the pull
    row stays what was asked for, since that is the address that will still make
    sense next month.

    `file` reads the rankings from a local file instead of the network — the
    only way to pull a `from_file` source, whose site will not serve a script,
    and usable for any other when a saved copy is what you have. The URL is
    still recorded as where the file came from, and the note names the file.

    Rows that do not match a player are stored anyway, with a null `player_key`
    — an unmatched name is a signal about `names.normalize`, and throwing it
    away would hide the miss. Raises only on an unknown source; a fetch, resolve
    or parse failure is recorded on the pull row and returned on the result.
    """
    if source not in SOURCES:
        known = ", ".join(sorted(SOURCES))
        raise RuntimeError(f"Unknown ranking source {source!r}. Known: {known}")

    src = SOURCES[source]
    if src.from_file and not file:
        # A usage error, not a failed pull: nothing was attempted, so no pull row.
        raise RuntimeError(
            f"{source} cannot be fetched — its site blocks scripts. Download its "
            f"export from {src.url} in a browser and pass it with --file."
        )

    with db.connect() as con:
        db.init_schema(con)
        remembered = db.last_ranking_url(con, source) if src.remembers_url else None
        source_url = url or remembered or src.url
        ranking_pull_id = db.new_ranking_pull(con, source, source_url)
        result = RankingPullResult(
            ranking_pull_id=ranking_pull_id,
            source=source,
            source_url=source_url,
            remembered=src.remembers_url,
        )

        try:
            if file:
                result.fetched_url = f"file:{Path(file).name}"
                rows = src.parse(Path(file).expanduser().read_text(encoding="utf-8-sig"))
            else:
                fetch_url = src.resolve(source_url, fetch.get) if src.resolve else source_url
                result.fetched_url = fetch_url
                rows = src.parse(fetch.get(fetch_url))
        except Exception as exc:
            logger.warning("ranking pull %s failed: %s", source, exc)
            result.error = str(exc)
            db.complete_ranking_pull(con, ranking_pull_id, result.status, result.error)
            return result

        by_name = query.player_keys_by_name(con)

        payload = []
        for row in rows:
            name_key = normalize(row["player_name"])
            player_key = by_name.get(name_key)
            if player_key:
                result.matched += 1
            payload.append({
                "ranking_pull_id": ranking_pull_id,
                "source": source,
                "rank": row.get("rank"),
                "player_name": row.get("player_name"),
                "player_name_key": name_key,
                "player_key": player_key,
                "team_abbr": row.get("team_abbr"),
                "positions": row.get("positions") or [],
                "age": row.get("age"),
                "extra": json.dumps(row.get("extra") or {}),
            })

        db.insert_ranking_rows(con, payload)
        result.rows = len(payload)

        note = f"{result.matched}/{result.rows} matched to the league snapshot" if result.rows else "no rows parsed"
        if result.fetched_url and result.fetched_url != source_url:
            # Which document these numbers actually came from, kept because a
            # resolved URL (an edition of a sheet) outlives the page linking to it,
            # and a file read leaves nothing else saying which export it was.
            note = f"{note}; fetched {result.fetched_url}"
        db.complete_ranking_pull(con, ranking_pull_id, result.status, note)

    return result
