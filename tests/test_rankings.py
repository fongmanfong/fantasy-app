"""
The ranking-site scraper, with no network.

The fixture mirrors HashtagBasketball's actual card markup (see
fantasy/sources/rankings/hashtagbasketball.py), including two edge cases pulled from a real
pull that used to silently drop rows: a player with no position badge, and a player
whose "Keeper Value" span is present but empty.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy.sources.rankings.hashtagbasketball import parse_dynasty

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


CARD = """
<div class="card dyn-card">
    <div class="dyn-head" onclick="dynTog(this)">
        <div class="dyn-rank">4<span class="dyn-trend"><i class="fa fa-arrows-h"></i> </span></div>
        <div>
            <div class="dyn-name">Nikola Jokic <span class="small"></span></div>
            <div class="dyn-meta">
                <span class="badge badge-light-secondary">C</span>
                <span class="badge badge-light-secondary">DEN</span>
                <span class="badge badge-light-secondary">30.5yo</span>
            </div>
        </div>
    </div>
    <div class="dyn-drawer">
        <div class="dyn-body">
            <div class="dyn-values">
                <div class="alert alert-warning"><strong>Dynasty</strong><span class="v">#4</span></div>
                <div class="alert alert-warning"><strong>Keeper</strong><span class="v">#4</span></div>
                <div class="alert alert-warning"><strong>Keeper Value</strong><span class="v">2309</span></div>
            </div>
            <h5 class="mt-2 mb-1">Dynasty Outlook</h5>
            <div class="dyn-outlook">Still the <b>best</b> passing big
                in the league.</div>
        </div>
    </div>
</div>
"""

# No position badge (some deep free agents carry none) — just team + age.
CARD_NO_POSITION = """
<div class="card dyn-card">
    <div class="dyn-head" onclick="dynTog(this)">
        <div class="dyn-rank">250<span class="dyn-trend"><i class="fa fa-arrow-circle-down"></i> 5</span></div>
        <div>
            <div class="dyn-name">Henri Veesaar <span class="small"></span></div>
            <div class="dyn-meta">
                <span class="badge badge-light-secondary">ATL</span>
                <span class="badge badge-light-secondary">22.4yo</span>
            </div>
        </div>
    </div>
    <div class="dyn-drawer">
        <div class="dyn-body">
            <div class="dyn-values">
                <div class="alert alert-warning"><strong>Dynasty</strong><span class="v">#250</span></div>
                <div class="alert alert-warning"><strong>Keeper</strong><span class="v"></span></div>
                <div class="alert alert-warning"><strong>Keeper Value</strong><span class="v"></span></div>
            </div>
        </div>
    </div>
</div>
"""

rows = parse_dynasty(CARD + CARD_NO_POSITION)

check("both cards parsed despite an empty value span", len(rows), 2)

jokic = rows[0]
check("rank", jokic["rank"], 4)
check("player_name", jokic["player_name"], "Nikola Jokic")
check("team_abbr", jokic["team_abbr"], "DEN")
check("positions", jokic["positions"], ["C"])
check("age", jokic["age"], 30.5)
check("extra", jokic["extra"], {"keeper_rank": 4, "keeper_value": 2309,
                               "outlook": "Still the best passing big in the league."})

veesaar = rows[1]
check("rank survives an empty sibling value span", veesaar["rank"], 250)
check("team_abbr still parses with no position badge", veesaar["team_abbr"], "ATL")
check("positions empty rather than swallowing the team", veesaar["positions"], [])
check("age", veesaar["age"], 22.4)
check("empty value span -> None rather than a crash", veesaar["extra"],
      {"keeper_rank": None, "keeper_value": None, "outlook": None})

# --- the outlook block ----------------------------------------------------
#
# It sits after the three values that complete a card, so it is attached to the
# row already appended. That is only safe while the note really does belong to
# the card that appended it, which is what the last two checks are about.

check("prose is collected through the tags inside it, whitespace collapsed",
      jokic["extra"]["outlook"], "Still the best passing big in the league.")
check("a card with no outlook gets None, not an empty string",
      veesaar["extra"]["outlook"], None)

both = parse_dynasty(CARD + CARD_NO_POSITION)
check("a later card without prose does not inherit the earlier card's",
      [r["extra"]["outlook"] for r in both],
      ["Still the best passing big in the league.", None])

# A card whose values never complete never reaches `rows`; its outlook must be
# dropped rather than land on whoever came before it.
INCOMPLETE = """
<div class="card dyn-card">
    <div class="dyn-head">
        <div class="dyn-rank">300</div>
        <div><div class="dyn-name">Broken Card <span class="small"></span></div>
        <div class="dyn-meta"><span class="badge">SAS</span></div></div>
    </div>
    <div class="dyn-drawer"><div class="dyn-body">
        <div class="dyn-values">
            <div class="alert"><strong>Dynasty</strong><span class="v">#300</span></div>
        </div>
        <div class="dyn-outlook">Belongs to nobody.</div>
    </div></div>
</div>
"""
orphan = parse_dynasty(CARD + INCOMPLETE)
check("an unfinished card contributes no row", len(orphan), 1)
check("and its outlook is not misfiled onto the previous player",
      orphan[0]["extra"]["outlook"], "Still the best passing big in the league.")

if failures:
    print(f"{len(failures)} FAILURE(S):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all ranking checks passed")
