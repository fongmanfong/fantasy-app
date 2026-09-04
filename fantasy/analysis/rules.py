"""
League rules the model depends on, read from the snapshot rather than assumed.

Every analysis run starts here. Anything the snapshot can tell us — which
categories the league scores, which of them inverts, whether it is head-to-head
at all — is derived from it, so pointing the tool at a second league, or at the
same league after a settings change, picks the new rules up automatically.

Anything the snapshot *cannot* tell us is recorded as an explicit
:class:`Fact` with `source="assumed"` and surfaced in the output, so the
assumptions are visible before the numbers rather than buried in a docstring.
Where an assumption would silently produce a wrong answer instead of a rough
one, `load` refuses.
"""
from dataclasses import dataclass, field

from ..query import CATEGORIES as DISPLAY

# Yahoo stat id -> the quantity the simulator models. Ids are stable; the stored
# `name` is not — snapshots taken before the stat-map fix have makes and
# attempts transposed — so the mapping is keyed on the id alone.
SIMULATED = {
    "5": "fg", "8": "ft", "10": "tpm", "12": "pts", "15": "reb",
    "16": "ast", "17": "stl", "18": "blk", "19": "tov",
}
# Yahoo's sort_order is 0 where a lower number wins. Older snapshots did not
# store it, so this is the fallback for the one category that inverts.
LOWER_WINS = {"19"}

# Scoring formats the model can represent. A points or roto league needs a
# different objective entirely, not a tweaked one.
SUPPORTED_SCORING = {"head"}

LABELS = {c["key"]: c for c in DISPLAY}


@dataclass(frozen=True)
class Fact:
    """One rule the model is running under, and where it came from."""
    label: str
    value: str
    source: str          # "yahoo" — read from the snapshot; "assumed" — not in it
    note: str = ""
    short: str = ""      # compact form for the one-line header

    def brief(self) -> str:
        return self.short or f"{self.label} {self.value}"


@dataclass
class Rules:
    league_key: str
    name: str
    season: int | None
    scoring_type: str
    categories: list[dict]
    games_per_week: float
    facts: list[Fact] = field(default_factory=list)

    @property
    def assumed(self) -> list[Fact]:
        return [f for f in self.facts if f.source == "assumed"]

    def summary(self) -> str:
        """One line naming what had to be assumed, for a command header."""
        if not self.assumed:
            return "all rules read from the snapshot"
        return "assumed: " + ", ".join(f.brief() for f in self.assumed)


def _scored_categories(con) -> tuple[list[dict], list[Fact]]:
    """The league's scoring categories, in the interface's display order."""
    rows = con.execute(
        "select stat_id, display_name, name, sort_order, is_only_display "
        "from v_stat_categories"
    ).fetchall()
    scored = [r for r in rows if not r[4]]

    if not scored:
        # An old snapshot with no settings step. Fall back rather than fail, but
        # say so — the nine standard categories are a guess about this league.
        return list(DISPLAY), [Fact(
            "categories", f"{len(DISPLAY)} standard", "assumed",
            "snapshot has no scoring categories; re-pull to read the real ones",
            short="standard 9 categories")]

    unsupported = [(r[0], r[1] or r[2]) for r in scored if r[0] not in SIMULATED]
    if unsupported:
        names = ", ".join(f"{n} (id {i})" for i, n in unsupported)
        raise RuntimeError(
            f"This league scores {len(unsupported)} categories the model cannot "
            f"simulate: {names}. Every scored category has to be simulated for "
            "the odds to mean anything, so the run is refused rather than "
            "quietly scoring a different league than yours.")

    by_key = {}
    facts = []
    for stat_id, display_name, name, sort_order, _ in scored:
        key = SIMULATED[stat_id]
        base = LABELS.get(key, {"key": key, "label": display_name or name})
        if sort_order is None:
            neg = stat_id in LOWER_WINS
        else:
            neg = int(sort_order) == 0
        by_key[key] = {**base, "key": key,
                       "label": display_name or base.get("label") or key,
                       "stat_id": stat_id, "neg": neg}

    if all(r[3] is None for r in scored):
        facts.append(Fact(
            "inverted category", "TO only", "assumed",
            "snapshot predates sort_order; re-pull to read it from Yahoo",
            short="TO inverted"))

    # Keep the interface's display order, restricted to what this league scores.
    ordered = [by_key[c["key"]] for c in DISPLAY if c["key"] in by_key]
    ordered += [v for k, v in by_key.items() if k not in {c["key"] for c in DISPLAY}]
    return ordered, facts


def load(con, games_per_week: float | None = None) -> Rules:
    """
    Read the rules for the snapshot's league, refusing what cannot be modelled.

    Raises if the league is not head-to-head categories, or scores anything the
    simulator has no quantity for.
    """
    row = con.execute(
        "select league_key, name, season, scoring_type, num_teams from v_leagues limit 1"
    ).fetchone()
    if not row:
        raise RuntimeError("No league in the snapshot. Run `fantasy pull` first.")
    league_key, name, season, scoring_type, num_teams = row

    if scoring_type not in SUPPORTED_SCORING:
        raise RuntimeError(
            f"{name} is a {scoring_type!r} league. The model scores a week by "
            "category wins, which only means something in head-to-head "
            "categories; a points or rotisserie league needs a different "
            "objective, so the run is refused.")

    categories, facts = _scored_categories(con)

    from .projection import GAMES_PER_WEEK
    gpw = GAMES_PER_WEEK if games_per_week is None else games_per_week

    facts = [
        Fact("scoring", f"head-to-head, {len(categories)} categories", "yahoo"),
        Fact("roster slots", _slot_summary(con), "yahoo"),
        *facts,
        # Not in the schema at all. Both are surfaced every run precisely
        # because a league can change them and the snapshot will not notice.
        Fact("lineups", "daily", "assumed",
             "every non-IL player accrues every game; a weekly-locked league "
             "would count only its 11 starters",
             short="daily lineups"),
        Fact("lineup management", "perfect", "assumed",
             "models the ceiling of daily streaming, not a real manager",
             short="perfect management"),
        Fact("games per team", f"{gpw}/week", "assumed",
             "no NBA schedule in the snapshot; override with --games",
             short=f"{gpw} games/team"),
        Fact("acquisition limits", "none", "assumed",
             "max adds per week/season are not pulled, so an add costs nothing",
             short="unlimited adds"),
    ]
    return Rules(league_key=league_key, name=name, season=season,
                 scoring_type=scoring_type, categories=categories,
                 games_per_week=gpw, facts=facts)


def _slot_summary(con) -> str:
    rows = con.execute(
        "select position, count from v_roster_positions").fetchall()
    active = sum(c or 0 for p, c in rows if p not in ("BN", "IL", "IL+", "IL-"))
    bench = sum(c or 0 for p, c in rows if p in ("BN",))
    il = sum(c or 0 for p, c in rows if p.startswith("IL"))
    return f"{active} active, {bench} bench, {il} IL"
