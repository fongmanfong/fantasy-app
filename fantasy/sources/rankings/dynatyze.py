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

That block is capped at whatever tier a logged-out visitor gets (currently ranks
1-75ish) and it carries no age, so `age` is always None here; `extra` carries the
one dynatyze-specific figure, its 0-9999 dynasty value.

**There is no commentary to capture here.** A Person entry carries name, url,
jobTitle, affiliation and the dynasty value — no prose. Nor is there any on the
per-player profile pages `extra["profile_url"]` points at: those render client
side and serve an empty shell. Dynatyze also publishes a sanctioned
machine-readable board at `dynasty-rankings.md` (announced in its own llms.txt,
also reachable with `Accept: text/markdown`), and that is likewise five columns
of rank, player, position, team and value with no notes. It is worth knowing
about for other reasons — it tags picks as position `PICK` on team `DRAFT`,
which is sturdier than matching their names, and it shows the same 68 rows with
the same seven gaps, confirming those are dynatyze's own and not a scraping
artefact — but it carries nothing this parser is missing.

Two things about what it contains. Future draft picks are ranked inline with the
players and do come through as Person entries ("2027 Early 1st" at #41 as of the
July 2026 list), so a caller ranking *players* has to drop them — analysis/
composite.py does. And the block is **sparser than its own numbering**: a handful
of positions inside the top 75 carry no element at all, so the ranks are not
contiguous and the row count is short of the deepest rank. Whoever holds those
slots does not reach this scrape. Do not renumber to close the gaps — the ranks
are dynatyze's, and a missing one is information.
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
            continue  # anything but a ranked entity, should the block gain one
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
