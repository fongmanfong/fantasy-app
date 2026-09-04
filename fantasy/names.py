"""
Standardizes a player name into a loose join key, for matching a name as printed by
an external source (a ranking site today, box scores or a schedule feed later) against
`v_players.full_name` from the Yahoo snapshot.

Three gaps close here, each picked because it is deterministic rather than a guess:

1. Case, punctuation and suffixes ("Jr.", "III") — sites disagree on these freely.
2. Diacritics — Yahoo's own names carry them ("Nikola Jokić", "Luka Dončić") but a
   scrape sometimes flattens them to ASCII ("Nikola Jokic"), or vice versa.
3. A short table of common first-name nicknames (below) — deliberately conservative,
   never a surname. Matching on a shared, unaltered surname keeps this safe even
   when the alias is wrong for a given player, unlike fuzzy matching on the surname
   itself, which routinely pairs unrelated players who happen to share a last name
   (e.g. "Josh Green" and "Jalen Green").

What this does *not* do: edit distance, initials-only matching, or anything else
that could pair two different players. A genuine mismatch — a stage name, a
transliteration the alias table doesn't know — is left unmatched rather than
silently paired with the wrong player.
"""
import re
import unicodedata

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")
_PUNCT = re.compile(r"[.'\-]")

# Each group is one person's set of interchangeable first names/nicknames; every
# member maps to the group's first entry, so any member survives normalize() as
# the same canonical token as its groupmates. Extend this table as new mismatches
# turn up in `fantasy rankings` output — don't guess ones that haven't.
_NICKNAME_GROUPS = [
    ("nic", "nicolas", "nick", "nicholas"),
    ("alex", "alexander", "alexandre"),
    ("cam", "cameron"),
    ("mike", "michael"),
    ("chris", "christopher"),
    ("matt", "matthew"),
    ("zach", "zachary", "zack"),
    ("josh", "joshua"),
    ("nate", "nathan", "nathaniel"),
    ("will", "william"),
    ("rob", "robert"),
    ("dan", "daniel", "danny"),
    ("tony", "anthony"),
    ("steph", "stephen", "steve", "steven"),
    ("vince", "vincent"),
    ("ben", "benjamin"),
    ("sam", "samuel"),
    ("andy", "andrew"),
    ("herb", "herbert"),
    ("mo", "moses", "mohamed"),
]

_NICKNAMES = {alias: group[0] for group in _NICKNAME_GROUPS for alias in group}


def _strip_accents(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(name: str) -> str:
    """Loose match key: lowercase, ASCII, no punctuation/suffix, nicknames folded."""
    name = _strip_accents(name)
    name = _PUNCT.sub("", name.lower())
    name = _SUFFIX.sub("", name)
    tokens = name.split()
    if tokens:
        tokens[0] = _NICKNAMES.get(tokens[0], tokens[0])
    return " ".join(tokens)
