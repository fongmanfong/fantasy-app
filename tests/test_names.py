"""
fantasy/names.py — the shared join key for matching an external source's spelling
of a player name against Yahoo's `v_players.full_name`.

Cases below are drawn from a real hashtag_dynasty pull against the league snapshot:
before diacritic-folding and the nickname table, "Nikola Jokic" (source) failed to
match "Nikola Jokić" (Yahoo), and "Nicolas Claxton" (source) failed to match Yahoo's
"Nic Claxton".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy.names import normalize

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n    expected: {expected!r}\n    actual:   {actual!r}")


check("case and punctuation", normalize("Jaron Pierre Jr."), normalize("jaron pierre"))
check("suffix stripped", normalize("Jaron Pierre Jr."), "jaron pierre")
check("apostrophe stripped", normalize("De'Aaron Fox"), "deaaron fox")
check("hyphen stripped", normalize("Shai Gilgeous-Alexander"), "shai gilgeousalexander")

# --- diacritics: Yahoo carries them, a scrape doesn't always ---

check("Jokic vs Jokić", normalize("Nikola Jokic"), normalize("Nikola Jokić"))
check("Doncic vs Dončić", normalize("Luka Doncic"), normalize("Luka Dončić"))
check("Sengun vs Sengün", normalize("Alperen Sengun"), normalize("Alperen Sengün"))
check("Valanciunas vs Valančiūnas", normalize("Jonas Valanciunas"), normalize("Jonas Valančiūnas"))
check("Porzingis vs Porziņģis", normalize("Kristaps Porzingis"), normalize("Kristaps Porziņģis"))

# --- nicknames: first token only, never the surname ---

check("Alexandre vs Alex Sarr", normalize("Alexandre Sarr"), normalize("Alex Sarr"))
check("Nicolas vs Nic Claxton", normalize("Nicolas Claxton"), normalize("Nic Claxton"))
check("unrelated same-surname players stay distinct",
      normalize("Josh Green") == normalize("Jalen Green"), False)

if failures:
    print(f"{len(failures)} FAILURE(S):\n")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all name-standardizer checks passed")
