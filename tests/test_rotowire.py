"""
The RotoWire scraper, with no network.

Fixture mirrors the real article (see fantasy/sources/rankings/rotowire.py): a
headline, a header row rendered as `<td>` rather than `<th>`, player rows whose
name cell is a link, and a second table after the rankings that must be ignored.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy.sources.rankings.rotowire import parse_dynasty

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


HTML = """
<html><body>
<h1 class="article__headline">Fantasy Basketball Dynasty Rankings 2026-27: Top 100 NBA Keeper Rankings</h1>
<p>Building a champion in NBA dynasty and keeper leagues takes more than a hot redraft season.</p>
<table class="ck-table-resized"><colgroup><col style="width:21.55%;"></colgroup><tbody>
<tr><td class="no-wrap">Keeper/Dynasty Ranking</td><td>Player</td><td>Team</td><td>Age</td></tr>
<tr><td>1</td><td class="no-wrap"><a href="https://www.rotowire.com/basketball/player/victor-wembanyama-5809">Victor Wembanyama</a></td><td>SAS</td><td>22</td></tr>
<tr><td>2</td><td class="no-wrap"><a href="https://www.rotowire.com/basketball/player/nikola-jokic-3612">Nikola Jokic</a></td><td>DEN</td><td>31</td></tr>
</tbody></table>
<p>Cameron Boozer (No. 15) is the top rookie in the rankings.</p>
<table><tr><td>9</td><td>Not A Ranking</td><td>XXX</td><td>40</td></tr></table>
</body></html>
"""

rows = parse_dynasty(HTML)
check("header row and any later table are skipped", len(rows), 2)

wemby = rows[0]
check("rank", wemby["rank"], 1)
check("player_name", wemby["player_name"], "Victor Wembanyama")
check("team_abbr", wemby["team_abbr"], "SAS")
check("no positions published", wemby["positions"], [])
check("age", wemby["age"], 22.0)
check("extra carries the profile url + the edition headline", wemby["extra"], {
    "profile_url": "https://www.rotowire.com/basketball/player/victor-wembanyama-5809",
    "edition": "Fantasy Basketball Dynasty Rankings 2026-27: Top 100 NBA Keeper Rankings",
})
check("second row", (rows[1]["rank"], rows[1]["player_name"]), (2, "Nikola Jokic"))

check("no table returns no rows rather than raising",
      parse_dynasty("<html><h1>moved</h1></html>"), [])

if failures:
    print(f"{len(failures)} FAILURE(S):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all rotowire checks passed")
