"""
Pure parser for LineupExperts' dynasty draft rankings, from the CSV the site exports.

https://www.lineupexperts.com/basketball/dynasty-draft-rankings

**This source cannot be fetched.** The page sits behind Cloudflare's JavaScript
challenge, so any request that is not a real browser gets a 403 "Just a moment..."
interstitial with no rankings in it. Getting past that would mean impersonating a
browser to defeat a control the site put there on purpose, so the source is
registered `from_file=True` instead: the user downloads the CSV the page offers and
`fantasy rankings pull lineupexperts_dynasty --file <csv>` reads it. Refreshing it
means downloading it again.

The export is three columns, and the middle one packs three fields into one cell,
padded apart with a long run of spaces:

    "Rank","Player","Age"
    "1","Victor Wembanyama          ...          SA - C","22"
    "4","Jayson Tatum               ...          BOS - PF,SF","28"

so the name is everything before the padding, and what follows it is
`TEAM - POS[,POS]`. A row whose cell does not split that way keeps the whole cell
as its name rather than being dropped — an odd name in `rankings show` is a
visible miss, a missing row is not.

Team codes are ESPN's (`SA`, `NO`, `NY`, `GS`, `UTAH`, `WSH`), not the NBA's three
letters the other sources print. They are rewritten here because the composite
takes a player's team from whichever source it reads first, and a mix of the two
spellings would make the same club look like two. `N/A` — a player with no team
at the time of the export — becomes None.

The 2026-27 export is 431 players, ranks contiguous from 1, every age present.
It carries no commentary and no edition label; the pull row's note records which
file it was read from.
"""
import csv
import io
import re

DYNASTY_URL = "https://www.lineupexperts.com/basketball/dynasty-draft-rankings"

_PLAYER_RE = re.compile(r"^(?P<name>.*?)\s{2,}(?P<team>\S+) - (?P<pos>\S+)$")

# ESPN team codes -> the NBA's own, for the six where they differ.
_TEAM = {"SA": "SAS", "NO": "NOP", "NY": "NYK", "GS": "GSW", "UTAH": "UTA", "WSH": "WAS"}


def _team(code: str) -> str | None:
    if code.upper() == "N/A":
        return None
    return _TEAM.get(code, code)


def parse_dynasty(text: str) -> list[dict]:
    """Ranking rows from the exported CSV. A file with no Rank/Player columns yields `[]`."""
    rows = []
    for rec in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        rank, cell = (rec.get("Rank") or "").strip(), (rec.get("Player") or "").strip()
        if not rank.isdigit() or not cell:
            continue
        match = _PLAYER_RE.match(cell)
        if match:
            name, team = match["name"], _team(match["team"])
            positions = [p for p in match["pos"].split(",") if p]
        else:
            name, team, positions = " ".join(cell.split()), None, []
        try:
            age = float(rec.get("Age") or "")
        except ValueError:
            age = None
        rows.append({
            "rank": int(rank),
            "player_name": name,
            "team_abbr": team,
            "positions": positions,
            "age": age,
            "extra": {},
        })
    return rows
