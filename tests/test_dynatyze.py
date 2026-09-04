"""
The dynatyze.com scraper, with no network.

Fixture mirrors the real page's embedded JSON-LD (see fantasy/sources/dynatyze.py):
an ItemList of Person entries (players) with draft picks omitted as a non-Person
entity, inside a @graph that also carries an unrelated WebPage node. Ranks 1 and 3
(a gap at 2, standing in for an omitted pick) mirror the real page's numbering.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy.sources.dynatyze import parse_dynasty

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


HTML = """
<html><head>
<script id="basketball-dynasty-rankings-jsonld" type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "WebPage", "url": "https://dynatyze.com/basketball/dynasty-rankings"},
  {"@type": "ItemList", "numberOfItems": 2, "itemListElement": [
    {"@type": "ListItem", "position": 1, "item": {"@type": "Person",
      "name": "Victor Wembanyama", "url": "https://dynatyze.com/basketball/players/victor-wembanyama",
      "jobTitle": "C", "affiliation": {"@type": "SportsTeam", "name": "SAS"},
      "additionalProperty": {"@type": "PropertyValue", "name": "Dynasty Value", "value": 9999}}},
    {"@type": "ListItem", "position": 3, "item": {"@type": "Person",
      "name": "Luka Doncic", "url": "https://dynatyze.com/basketball/players/luka-doncic",
      "jobTitle": "G", "affiliation": {"@type": "SportsTeam", "name": "LAL"},
      "additionalProperty": {"@type": "PropertyValue", "name": "Dynasty Value", "value": 9804}}}
  ]}
]}
</script>
</head><body></body></html>
"""

rows = parse_dynasty(HTML)
check("player count (the rank-2 pick is omitted, not a parse error)", len(rows), 2)

wemby = rows[0]
check("rank", wemby["rank"], 1)
check("player_name", wemby["player_name"], "Victor Wembanyama")
check("team_abbr", wemby["team_abbr"], "SAS")
check("positions", wemby["positions"], ["C"])
check("age unavailable from this source", wemby["age"], None)
check("extra carries the dynasty value + profile url", wemby["extra"], {
    "dynasty_value": 9999,
    "profile_url": "https://dynatyze.com/basketball/players/victor-wembanyama",
})

check("rank preserved across the gap left by an omitted pick", rows[1]["rank"], 3)

check("missing JSON-LD block returns no rows rather than raising",
      parse_dynasty("<html>no jsonld here</html>"), [])

if failures:
    print(f"{len(failures)} FAILURE(S):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all dynatyze checks passed")
