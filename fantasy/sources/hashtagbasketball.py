"""
Pure parser for HashtagBasketball's dynasty rankings page.

https://hashtagbasketball.com/fantasy-basketball-dynasty-rankings

This is a scrape of a template, not an API — the shape below is hard-won from reading
the rendered markup rather than documented anywhere, and a redesign of the site is a
one-file fix here rather than a data outage across the app. No network in this module;
see fetch.py for that.
"""
from html.parser import HTMLParser

DYNASTY_URL = "https://hashtagbasketball.com/fantasy-basketball-dynasty-rankings"


def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
    for name, value in attrs:
        if name == "class" and value:
            return set(value.split())
    return set()


class _DynastyParser(HTMLParser):
    """
    One `<div class="card dyn-card">` per player:

        <div class="dyn-rank">4<span class="dyn-trend">...</span></div>
        <div class="dyn-name">Nikola Jokic <span class="small"></span></div>
        <div class="dyn-meta">
            <span class="badge ...">C</span>
            <span class="badge ...">DEN</span>
            <span class="badge ...">30.5yo</span>
        </div>
        ...
        <div class="dyn-values">
            <div class="alert ..."><strong>Dynasty</strong><span class="v">#4</span></div>
            <div class="alert ..."><strong>Keeper</strong><span class="v">#4</span></div>
            <div class="alert ..."><strong>Keeper Value</strong><span class="v">2309</span></div>
        </div>

    The last badge is always an age ("30.5yo"), the one before it a team code;
    anything earlier is eligible positions, which — unlike the team — can be absent
    (a handful of deep free agents carry no position badge at all). A card is
    complete — and appended to `rows` — the moment
    all three dyn-values labels have been seen (a value span can be empty, so the count
    is checked on the closing tag, not on receiving text), which avoids having to track
    div-nesting depth to find where a card actually ends.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._mode: str | None = None
        self._skip = 0
        self._cur: dict | None = None
        self._label: str | None = None

    def handle_starttag(self, tag, attrs):
        classes = _classes(attrs)
        if tag == "div" and "dyn-card" in classes:
            self._cur = {"_name": "", "badges": [], "values": {}}
            self._mode = None
            return
        if self._cur is None:
            return
        if tag == "div" and "dyn-name" in classes:
            self._mode = "name"
        elif tag == "span" and "small" in classes:
            # A trailing note span next to the player name — no field of ours lives
            # inside it, but it can be non-empty (trade/injury flags), so skip its text.
            self._skip += 1
        elif tag == "span" and "badge" in classes:
            self._mode = "badge"
        elif tag == "strong":
            self._mode = "label"
        elif tag == "span" and "v" in classes:
            self._mode = "value"
            if self._label:
                self._cur["values"].setdefault(self._label, "")

    def handle_endtag(self, tag):
        if tag == "span" and self._skip:
            self._skip -= 1
            return
        if tag == "span" and self._mode == "badge":
            self._mode = None
        elif tag == "span" and self._mode == "value":
            self._mode = None
            if self._cur is not None and len(self._cur["values"]) == 3:
                self._finish_card()
        elif tag == "strong":
            self._mode = None

    def handle_data(self, data):
        if self._skip or self._cur is None or self._mode is None:
            return
        if self._mode == "name":
            self._cur["_name"] += data
        elif self._mode == "badge":
            text = data.strip()
            if text:
                self._cur["badges"].append(text)
        elif self._mode == "label":
            self._label = data.strip()
        elif self._mode == "value" and self._label:
            self._cur["values"][self._label] = data.strip()

    def _finish_card(self):
        cur, self._cur = self._cur, None
        badges = cur["badges"]
        age = None
        team = None
        if badges and badges[-1].endswith("yo"):
            try:
                age = float(badges[-1][:-2])
            except ValueError:
                age = None
            badges = badges[:-1]
        if badges:
            team = badges[-1]
            badges = badges[:-1]

        values = cur["values"]

        def rank_of(label: str) -> int | None:
            raw = values.get(label, "").lstrip("#")
            return int(raw) if raw.isdigit() else None

        self.rows.append({
            "rank": rank_of("Dynasty"),
            "player_name": " ".join(cur["_name"].split()),
            "team_abbr": team,
            "positions": badges,
            "age": age,
            "extra": {
                "keeper_rank": rank_of("Keeper"),
                "keeper_value": rank_of("Keeper Value"),
            },
        })


def parse_dynasty(html: str) -> list[dict]:
    parser = _DynastyParser()
    parser.feed(html)
    return parser.rows
