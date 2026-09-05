"""
Registry of ranking sites this app knows how to scrape.

Each entry pairs a default URL with a pure `parse(text) -> list[dict]` function — no
network inside the parser, mirroring yahoo/parse.py vs yahoo/client.py, and for the
same reason: the parser is what breaks when a site changes its template, and it is
the part worth testing against a saved fixture rather than a live page. `text` is
whatever the source serves: HTML for the two scrapes, CSV for angle.

Row dicts share a common shape:
    rank         int | None   — the source's primary ranking
    player_name  str          — as printed by the source, matched against v_players
    team_abbr    str | None
    positions    list[str]
    age          float | None
    extra        dict         — anything source-specific (other rankings, values, ...)

Add a new site by writing one module with a `parse_xxx(text)` function next to
hashtagbasketball.py and registering it below — nothing else in the app changes.
"""
from collections.abc import Callable
from dataclasses import dataclass

from . import angle, dynatyze, hashtagbasketball


@dataclass(frozen=True)
class Source:
    """
    One ranking site: where to fetch it, and the pure parser for what comes back.

    The two optional fields exist for sources that have no permanent home — angle
    publishes each update as a new post pointing at a new Google Sheet:

    `resolve` runs before the fetch and turns the URL the user has to hand into
    the one actually worth downloading. It is given the shared fetcher rather
    than importing it, so a resolver that has to read a page to find the real
    link is still testable without the network.

    `remembers_url` makes the *last successfully pulled* URL the default for the
    next pull, so a `--url` pointing at a newer edition only has to be given
    once. `url` is then a seed for the first pull rather than a fixed address.
    """
    url: str
    parse: Callable[[str], list[dict]]
    resolve: Callable[[str, Callable[[str], str]], str] | None = None
    remembers_url: bool = False


SOURCES: dict[str, Source] = {
    "hashtag_dynasty": Source(
        url=hashtagbasketball.DYNASTY_URL,
        parse=hashtagbasketball.parse_dynasty,
    ),
    "dynatyze_dynasty": Source(
        url=dynatyze.DYNASTY_URL,
        parse=dynatyze.parse_dynasty,
    ),
    "angle_dynasty": Source(
        url=angle.DYNASTY_URL,
        parse=angle.parse_dynasty,
        resolve=angle.resolve,
        remembers_url=True,
    ),
}
