"""
The Angle dynasty rankings source, with no network.

The CSV fixture mirrors the real published sheet (see fantasy/sources/rankings/angle.py):
a title and a mobile tip above the header, a second always-empty "Movement" spacer
column, a player cell whose positions carry an internal comma, "UR" for a player one
ranker left off, and blank rows padding the bottom of the sheet.

The URL cases are the point of this source — the sheet moves between editions, so
`resolve` has to accept the article, the embedded sheet, or a CSV link alike.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy.sources.rankings.angle import csv_url, parse_dynasty, resolve, sheet_in_page

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


CSV = (
    ',"Tip: If you\'re on mobile, scroll right to see our individual & AVG ranks!",'
    '"Top 300 9-Cat Dynasty Rankings \nJuly 2026 ",,,,,,\n'
    ",,,,,,,,\n"
    "Rank ,Movement,Player,Age,Movement,Andrew,Braxton ,Mitchell,Average Rank\n"
    '1,-,"Victor Wembanyama (SA - F,C)",22.7,,1,1,1,1.0\n'
    "5,⇧1,Cooper Flagg (DAL - F),19.7,,5,6,3,4.7\n"
    "317,NEW,Landry Shamet (NY - G),29.5,,UR,298,UR,312.7\n"
    ",,,,,,,,\n"
)

rows = parse_dynasty(CSV)

check("blank padding rows dropped", len(rows), 3)

wemby = rows[0]
check("rank", wemby["rank"], 1)
check("name split off the team/position parenthetical", wemby["player_name"], "Victor Wembanyama")
check("team", wemby["team_abbr"], "SA")
check("positions survive the comma inside the cell", wemby["positions"], ["F", "C"])
check("age", wemby["age"], 22.7)
check("extra", wemby["extra"], {
    "average_rank": 1.0,
    "movement": "-",
    "ranks": {"Andrew": 1, "Braxton": 1, "Mitchell": 1},
    "edition": "Top 300 9-Cat Dynasty Rankings July 2026",
})

check("single position", rows[1]["positions"], ["F"])
check("movement read from the leftmost of the two Movement columns",
      rows[1]["extra"]["movement"], "⇧1")

shamet = rows[2]
check("UR means unranked by that ranker, not a parse failure",
      shamet["extra"]["ranks"], {"Andrew": None, "Braxton": 298, "Mitchell": None})
check("consensus average still read", shamet["extra"]["average_rank"], 312.7)

# The rankers are people, and the column set changes when they do.
RENAMED = (
    "Rank,Player,Age,Jordan,Average Rank\n"
    "1,Victor Wembanyama (SA - C),22.7,1,1.0\n"
)
renamed = parse_dynasty(RENAMED)
check("a different set of rankers is read from the header, not assumed",
      renamed[0]["extra"]["ranks"], {"Jordan": 1})
check("a missing Movement column is not an error", renamed[0]["extra"]["movement"], None)
check("no title row above the header -> no edition", renamed[0]["extra"]["edition"], None)

check("a sign-in page or a re-laid-out sheet is an empty pull, not an exception",
      parse_dynasty("<html>Sign in to continue</html>"), [])

# --- URL forms ---------------------------------------------------------------

PUBHTML = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vSF3trd/pubhtml"
           "?gid=0&single=true&widget=true&headers=false")
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSF3trd/pub?gid=0&single=true&output=csv"

check("the embedded published sheet rewrites to its CSV export", csv_url(PUBHTML), CSV_URL)
check("an already-CSV link is left pointing at the same export",
      csv_url(CSV_URL), CSV_URL)
check("a normal sheet uses the other export endpoint, keeping the tab",
      csv_url("https://docs.google.com/spreadsheets/d/1AbC/edit#gid=7"),
      "https://docs.google.com/spreadsheets/d/1AbC/export?format=csv&gid=7")
check("an article is not a sheet URL",
      csv_url("https://anglefantasybasketball.com/2026/07/23/top-300/"), None)

POST = (
    '<article><p>Our July rankings:</p>'
    '<iframe src="https://docs.google.com/spreadsheets/d/e/2PACX-1vSF3trd/pubhtml'
    '?gid=0&#038;single=true&#038;widget=true&#038;headers=false" width="100%"></iframe>'
    "</article>"
)

check("the sheet is found in the post and its entities unescaped",
      sheet_in_page(POST),
      "https://docs.google.com/spreadsheets/d/e/2PACX-1vSF3trd/pubhtml"
      "?gid=0&single=true&widget=true&headers=false")

fetched = []


def fake_get(url):
    fetched.append(url)
    return POST


check("an article resolves to the CSV behind it",
      resolve("https://anglefantasybasketball.com/2026/07/23/top-300/", fake_get),
      CSV_URL)
check("resolving an article costs exactly one fetch", len(fetched), 1)

check("a sheet URL resolves without touching the network",
      resolve(PUBHTML, fake_get), CSV_URL)
check("still one fetch", len(fetched), 1)

try:
    resolve("https://anglefantasybasketball.com/2026/07/23/top-300/", lambda url: "<p>no sheet</p>")
    failures.append("a post with no embedded sheet should raise, not return a bad URL")
except RuntimeError:
    pass

if failures:
    print(f"{len(failures)} FAILURE(S):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all angle checks passed")
