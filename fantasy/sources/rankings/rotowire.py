"""
Pure parser for RotoWire's annual dynasty/keeper rankings article.

https://www.rotowire.com/basketball/article/fantasy-basketball-dynasty-rankings-2026-27-136303

RotoWire publishes this as an ordinary editorial article, once per season, and each
edition is a new article with a new numeric id — so, like angle, the source is
registered `remembers_url=True` and a new season only needs `--url` once. Every row
carries the article's own headline as `extra["edition"]` for the same reason angle
carries its sheet title: the URL behind a stored pull will have moved on.

The rankings are a single server-rendered CKEditor table, the only `<table>` in the
article, whose first row is a header rendered as `<td>` rather than `<th>`:

    <tr><td>Keeper/Dynasty Ranking</td><td>Player</td><td>Team</td><td>Age</td></tr>
    <tr><td>1</td><td><a href=".../player/victor-wembanyama-5809">Victor Wembanyama</a></td>
        <td>SAS</td><td>22</td></tr>

A row counts only when its first cell is an integer, which is how the header is
skipped without depending on its wording. It is a Top 100 — ranks 1-100 contiguous
in the 2026-27 edition — with no positions (so `positions` is always `[]`) and a
whole-number age.

**There is no per-player commentary to capture.** The prose around the table is a
few article-level paragraphs about tiers ("Cameron Boozer (No. 15) is the top
rookie...") rather than a note beside each player, so it is not stored.
"""
from html.parser import HTMLParser

DYNASTY_URL = (
    "https://www.rotowire.com/basketball/article/"
    "fantasy-basketball-dynasty-rankings-2026-27-136303"
)


class _TableParser(HTMLParser):
    """Cells of every row of the first `<table>`, plus each row's first link and the headline."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[list[str], str | None]] = []
        self.headline: str | None = None
        self._in_h1 = False
        self._h1_text = ""
        self._tables_seen = 0
        self._in_table = False
        self._cells: list[str] | None = None
        self._cell: str | None = None
        self._href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "h1" and self.headline is None:
            self._in_h1 = True
        elif tag == "table":
            self._tables_seen += 1
            self._in_table = self._tables_seen == 1
        elif not self._in_table:
            return
        elif tag == "tr":
            self._cells, self._href = [], None
        elif tag == "td" and self._cells is not None:
            self._cell = ""
        elif tag == "a" and self._cells is not None and self._href is None:
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag == "h1" and self._in_h1:
            self._in_h1 = False
            self.headline = " ".join(self._h1_text.split()) or None
        elif tag == "table":
            self._in_table = False
        elif not self._in_table:
            return
        elif tag == "td" and self._cell is not None:
            self._cells.append(" ".join(self._cell.split()))
            self._cell = None
        elif tag == "tr" and self._cells is not None:
            self.rows.append((self._cells, self._href))
            self._cells = None

    def handle_data(self, data):
        if self._in_h1:
            self._h1_text += data
        if self._cell is not None:
            self._cell += data


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def parse_dynasty(html: str) -> list[dict]:
    """
    Ranking rows from the article's table. Returns `[]` when there is no table —
    the article changed shape — so the pull is recorded as empty rather than failed.
    """
    parser = _TableParser()
    parser.feed(html)
    rows = []
    for cells, href in parser.rows:
        if len(cells) < 2 or not cells[0].isdigit():
            continue  # the header row, or anything that is not a ranked player
        team = cells[2] if len(cells) > 2 and cells[2] else None
        age = _number(cells[3]) if len(cells) > 3 else None
        rows.append({
            "rank": int(cells[0]),
            "player_name": cells[1],
            "team_abbr": team,
            "positions": [],
            "age": age,
            "extra": {"profile_url": href, "edition": parser.headline},
        })
    return rows
