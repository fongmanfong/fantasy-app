"""
Registry of ranking sites this app knows how to scrape.

Each entry pairs a default URL with a pure `parse(html) -> list[dict]` function — no
network inside the parser, mirroring yahoo/parse.py vs yahoo/client.py, and for the
same reason: the parser is what breaks when a site changes its template, and it is
the part worth testing against a saved HTML fixture rather than a live page.

Row dicts share a common shape:
    rank         int | None   — the source's primary ranking
    player_name  str          — as printed by the source, matched against v_players
    team_abbr    str | None
    positions    list[str]
    age          float | None
    extra        dict         — anything source-specific (other rankings, values, ...)

Add a new site by writing one module with a `parse_xxx(html)` function next to
hashtagbasketball.py and registering it below — nothing else in the app changes.
"""
from dataclasses import dataclass
from typing import Callable

from . import hashtagbasketball


@dataclass(frozen=True)
class Source:
    url: str
    parse: Callable[[str], list[dict]]


SOURCES: dict[str, Source] = {
    "hashtag_dynasty": Source(
        url=hashtagbasketball.DYNASTY_URL,
        parse=hashtagbasketball.parse_dynasty,
    ),
}
