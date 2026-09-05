"""
Angle Fantasy Basketball's Top 300 9-cat dynasty rankings.

https://anglefantasybasketball.com — three rankers (currently Andrew, Braxton and
Mitchell) publish individual lists plus a consensus average.

Two things make this source different from the other two:

**The table is not on the page.** An Angle rankings post is a WordPress article
with a published Google Sheet in an `<iframe>`; the article HTML contains no
`<table>` at all. So this module fetches the sheet's own CSV export rather than
scraping rendered markup — which is both sturdier and cheaper than parsing the
`pubhtml` view. `resolve()` does that rewrite; `parse_dynasty()` is the pure part
and takes CSV text.

**The sheet moves.** Angle publishes each update as a new post pointing at a new
sheet, so unlike hashtagbasketball there is no permanent URL to hardcode. Three
things follow from that, and together they are the whole design here:

* `resolve()` accepts *whatever* the user has to hand — the article URL, the
  embedded `pubhtml` URL, a normal `/edit` sheet URL, or an `output=csv` link —
  and turns it into the CSV export. Only the article case costs a network round
  trip, and it is injected as `get` so this stays testable offline.
* `DYNASTY_URL` below is a seed, not a home. The registry marks this source
  `remembers_url=True`, so once a newer post is pulled with `--url` that URL
  becomes the default for later pulls (see `fantasy/rankings.py`).
* The sheet's own title row ("Top 300 9-Cat Dynasty Rankings July 2026") is
  carried on every row as `extra["edition"]`, so a stored ranking says which
  edition it came from even after the URL it came from has been superseded.

The parser reads the header row by name rather than by position, because the
individual rankers are people and the column set changes when the roster of
rankers does — any column that isn't one of the known ones is taken to be a
ranker and lands in `extra["ranks"]`.
"""
import csv
import html
import io
import re
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

# The July 2026 post — a starting point for the first pull, superseded by the last
# URL pulled. See the module docstring.
DYNASTY_URL = (
    "https://anglefantasybasketball.com/2026/07/23/"
    "top-300-dynasty-basketball-rankings-july-2026/"
)

_IFRAME_RE = re.compile(
    r'<iframe[^>]+src=["\']([^"\']*docs\.google\.com/spreadsheets/[^"\']*)["\']',
    re.I,
)

# "Victor Wembanyama (SA - F,C)" — one cell carrying name, team and positions, with
# a comma inside the parentheses that a naive split on "," would break on.
_PLAYER_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<team>[A-Z]{2,4})\s*-\s*(?P<pos>[^)]*)\)\s*$")

# Header labels that mean something specific to this parser. Anything else in the
# header row is one of the individual rankers.
_RANK = "rank"
_PLAYER = "player"
_AGE = "age"
_AVERAGE = "average rank"
_MOVEMENT = "movement"
_KNOWN = {_RANK, _PLAYER, _AGE, _AVERAGE, _MOVEMENT, ""}


def _gid(parts) -> str:
    """The sheet tab to export: from ?gid=, else #gid=, else the first tab."""
    for source in (parts.query, parts.fragment):
        values = parse_qs(source).get("gid")
        if values and values[0].isdigit():
            return values[0]
    return "0"


def csv_url(url: str) -> str | None:
    """
    The CSV export for a Google Sheets URL in any of the forms Angle hands out,
    or None if this isn't a Google Sheets URL at all (an article page, say).

    A *published* sheet (`/d/e/<token>/pubhtml`, what the iframe embeds) and a
    normal one (`/d/<id>/edit`) have different export endpoints and are not
    interchangeable: the publish token is not a spreadsheet id.
    """
    parts = urlsplit(url)
    if parts.netloc != "docs.google.com":
        return None

    published = re.match(r"^/spreadsheets/d/e/([^/]+)/", parts.path + "/")
    if published:
        return (f"https://docs.google.com/spreadsheets/d/e/{published.group(1)}"
                f"/pub?gid={_gid(parts)}&single=true&output=csv")

    private = re.match(r"^/spreadsheets/d/([^/]+)", parts.path)
    if private:
        return (f"https://docs.google.com/spreadsheets/d/{private.group(1)}"
                f"/export?format=csv&gid={_gid(parts)}")
    return None


def sheet_in_page(page_html: str) -> str | None:
    """The first embedded Google Sheet in an Angle post, unescaped."""
    match = _IFRAME_RE.search(page_html)
    return html.unescape(match.group(1)) if match else None


def resolve(url: str, get: Callable[[str], str]) -> str:
    """
    Turn whatever the user pointed at into the sheet's CSV export URL, fetching
    the page with `get` only when the URL is an article rather than a sheet.

    Raises when an article contains no embedded sheet: that is a URL the user
    supplied by hand, so a clear failure beats a pull that silently stores
    nothing.
    """
    direct = csv_url(url)
    if direct:
        return direct

    embedded = sheet_in_page(get(url))
    if not embedded:
        raise RuntimeError(
            f"No embedded Google Sheet found at {url}. Open the rankings post, "
            "copy the sheet's own URL, and pass it with --url."
        )
    resolved = csv_url(embedded)
    if not resolved:
        raise RuntimeError(f"Embedded sheet URL not understood: {embedded}")
    return resolved


def _norm(cell: str) -> str:
    return " ".join(cell.split()).lower()


def _header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    """
    Locate the header row and map each label to its column.

    The sheet opens with a title and a mobile-scrolling tip before the header, and
    the number of those rows is a formatting decision that changes between
    editions — so find the header by its content instead of assuming a row number.
    Duplicate labels keep the leftmost column: the sheet carries a second, always
    empty "Movement" spacer to the right of Age.
    """
    for index, row in enumerate(rows[:20]):
        labels = [_norm(cell) for cell in row]
        if _RANK in labels and _PLAYER in labels:
            columns: dict[str, int] = {}
            for column, label in enumerate(labels):
                if label:
                    columns.setdefault(label, column)
            return index, columns
    return None


def _edition(rows: list[list[str]], header_row: int) -> str | None:
    """The sheet's own title, from the rows above the header."""
    for row in rows[:header_row]:
        for cell in row:
            text = " ".join(cell.split())
            if "rank" in text.lower() and not text.lower().startswith("tip"):
                return text
    return None


def _int(cell: str) -> int | None:
    """An integer cell, or None for blanks and "UR" (unranked by that ranker)."""
    text = cell.strip()
    return int(text) if text.isdigit() else None


def _float(cell: str) -> float | None:
    try:
        return float(cell.strip())
    except ValueError:
        return None


def _split_player(cell: str) -> tuple[str, str | None, list[str]]:
    """"Name (TEAM - P1,P2)" into its three parts; the team is "FA" for free agents."""
    match = _PLAYER_RE.match(cell.strip())
    if not match:
        return " ".join(cell.split()), None, []
    positions = [p.strip() for p in match.group("pos").split(",") if p.strip()]
    return " ".join(match.group("name").split()), match.group("team"), positions


def parse_dynasty(text: str) -> list[dict]:
    """
    Ranking rows from the sheet's CSV export.

    Returns `[]` when no header row is recognisable — a re-laid-out sheet, or a
    URL that turned out to serve a Google sign-in page rather than a CSV, shows
    up as an empty pull rather than an exception, the same as the other sources.
    """
    rows = list(csv.reader(io.StringIO(text)))
    found = _header(rows)
    if not found:
        return []
    header_row, columns = found

    rankers = [label for label in columns if label not in _KNOWN]
    edition = _edition(rows, header_row)

    def cell(row: list[str], label: str) -> str:
        column = columns.get(label)
        return row[column] if column is not None and column < len(row) else ""

    out = []
    for row in rows[header_row + 1:]:
        name_cell = cell(row, _PLAYER).strip()
        if not name_cell:
            continue  # trailing blank rows padding the sheet
        name, team, positions = _split_player(name_cell)
        movement = cell(row, _MOVEMENT).strip()
        out.append({
            "rank": _int(cell(row, _RANK)),
            "player_name": name,
            "team_abbr": team,
            "positions": positions,
            "age": _float(cell(row, _AGE)),
            "extra": {
                "average_rank": _float(cell(row, _AVERAGE)),
                "movement": movement or None,
                "ranks": {label.title(): _int(cell(row, label)) for label in rankers},
                "edition": edition,
            },
        })
    return out
