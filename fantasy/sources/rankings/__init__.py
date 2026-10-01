"""
Registry of ranking sites this app knows how to scrape.

Each entry pairs a default URL with a pure `parse(text) -> list[dict]` function — no
network inside the parser, mirroring yahoo/parse.py vs yahoo/client.py, and for the
same reason: the parser is what breaks when a site changes its template, and it is
the part worth testing against a saved fixture rather than a live page. `text` is
whatever the source serves: HTML for the three scrapes, CSV for angle and for
lineupexperts — the last read from a file the user downloaded, not fetched.

Row dicts share a common shape:
    rank         int | None   — the source's primary ranking
    player_name  str          — as printed by the source, matched against v_players
    team_abbr    str | None
    positions    list[str]
    age          float | None
    extra        dict         — anything source-specific (other rankings, values, ...)

Add a new site by writing one module with a `parse_xxx(text)` function next to
hashtagbasketball.py and registering it below — nothing else in the app changes.
An entry's `kind` says which lists it is comparable with, and is the only thing
`fantasy rankings composite` uses to decide what to average together.
"""
from collections.abc import Callable
from dataclasses import dataclass

from . import angle, dynatyze, hashtagbasketball, lineupexperts, rotowire


@dataclass(frozen=True)
class Source:
    """
    One ranking site: where to fetch it, and the pure parser for what comes back.

    The two optional fields exist for sources that have no permanent home — angle
    publishes each update as a new post pointing at a new Google Sheet, rotowire
    each season as a new article:

    `resolve` runs before the fetch and turns the URL the user has to hand into
    the one actually worth downloading. It is given the shared fetcher rather
    than importing it, so a resolver that has to read a page to find the real
    link is still testable without the network.

    `remembers_url` makes the *last successfully pulled* URL the default for the
    next pull, so a `--url` pointing at a newer edition only has to be given
    once. `url` is then a seed for the first pull rather than a fixed address.

    `kind` is what the list is *of*. Sources only mean the same thing — and are
    only comparable, as `analysis/composite.py` compares them — when they rank
    on the same axis, so a redraft or keeper list registered here would carry a
    different kind and be composited separately rather than averaged in.

    `from_file` marks a source whose site will not serve its rankings to a
    script at all — lineupexperts sits behind a bot challenge — so a pull has to
    be given `--file`, the export the user downloaded in a browser, and refuses
    to try the network without one. `url` is then only provenance.
    """
    url: str
    parse: Callable[[str], list[dict]]
    kind: str = "dynasty"
    resolve: Callable[[str, Callable[[str], str]], str] | None = None
    remembers_url: bool = False
    from_file: bool = False


SOURCES: dict[str, Source] = {
    "hashtag_dynasty": Source(
        url=hashtagbasketball.DYNASTY_URL,
        parse=hashtagbasketball.parse_dynasty,
        kind="dynasty",
    ),
    "dynatyze_dynasty": Source(
        url=dynatyze.DYNASTY_URL,
        parse=dynatyze.parse_dynasty,
        kind="dynasty",
    ),
    "angle_dynasty": Source(
        url=angle.DYNASTY_URL,
        parse=angle.parse_dynasty,
        kind="dynasty",
        resolve=angle.resolve,
        remembers_url=True,
    ),
    "rotowire_dynasty": Source(
        url=rotowire.DYNASTY_URL,
        parse=rotowire.parse_dynasty,
        kind="dynasty",
        remembers_url=True,
    ),
    "lineupexperts_dynasty": Source(
        url=lineupexperts.DYNASTY_URL,
        parse=lineupexperts.parse_dynasty,
        kind="dynasty",
        from_file=True,
    ),
}
