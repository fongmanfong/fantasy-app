"""
Pure parser for dynatyze.com's NBA dynasty rankings page.

https://dynatyze.com/basketball/dynasty-rankings

dynatyze renders this page client-side: the visible table comes from an XHR to
`/api/rankings` after mount. That path is disallowed in dynatyze's robots.txt for
every user agent, so this deliberately does not call it — fetch.py only ever
requests the page URL itself, which robots.txt allows. Instead this reads the
`<script id="basketball-dynasty-rankings-jsonld">` block dynatyze embeds in that
same server-rendered HTML for SEO (a schema.org ItemList): same page, same
allowed path, no JS execution required.

That block only lists ranked players — draft picks are a separate, non-Person
entity dynatyze leaves out of it — and is capped at whatever tier a logged-out
visitor gets (currently ranks 1-75ish). It carries no age, so `age` is always
None here; `extra` carries the one dynatyze-specific figure, its 0-9999 dynasty
value.
"""
import json
import re

DYNASTY_URL = "https://dynatyze.com/basketball/dynasty-rankings"

_JSONLD_RE = re.compile(
    r'<script id="basketball-dynasty-rankings-jsonld" type="application/ld\+json">'
    r'(.*?)</script>',
    re.S,
)


def parse_dynasty(html: str) -> list[dict]:
    """
    Ranking rows from the embedded JSON-LD block. See the module docstring for
    why this reads the SEO markup rather than the site's own rankings API.

    Returns `[]` when the block is absent — the page rendered differently, or
    dynatyze changed its markup — rather than raising, so a scrape that finds
    nothing is recorded as an empty pull instead of an error.
    """
    match = _JSONLD_RE.search(html)
    if not match:
        return []  # markup changed or the page didn't render the block we expect

    graph = json.loads(match.group(1)).get("@graph", [])
    item_lists = [node for node in graph if node.get("@type") == "ItemList"]
    if not item_lists:
        return []

    rows = []
    for element in item_lists[0].get("itemListElement", []):
        item = element.get("item", {})
        if item.get("@type") != "Person":
            continue  # draft picks etc. aren't listed as Person entries
        position = item.get("jobTitle")
        value = next(
            (p["value"] for p in [item.get("additionalProperty", {})]
             if p.get("name") == "Dynasty Value"),
            None,
        )
        rows.append({
            "rank": element.get("position"),
            "player_name": item.get("name"),
            "team_abbr": item.get("affiliation", {}).get("name"),
            "positions": [position] if position else [],
            "age": None,
            "extra": {"dynasty_value": value, "profile_url": item.get("url")},
        })
    return rows
