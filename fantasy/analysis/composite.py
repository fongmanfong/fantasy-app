"""
One ranking out of several, and the reading of it back.

Every source in the registry ranks the same players against a different depth
and a different house view. `build` folds them into a single ordering; nothing
here writes — `fantasy/composite.py` owns the connection and the storing, the
same split as rankings.py vs sources/rankings/.

The method, and why each part of it is there:

**Rank becomes a value on a decay curve**, `100 * exp(-(rank-1)/CURVE)`.
Dynasty value is not linear in rank — the gap between #1 and #10 is worth far
more than the gap between #200 and #210 — so averaging raw ranks would treat a
disagreement in the tail as seriously as one at the top. CURVE=80 puts the
half-life around 55 ranks, making a top-15 asset worth roughly twice a top-70
one. Note that the curve sets the *scale* of the score and barely touches the
order: re-running the stored snapshot at CURVE from 40 to 200, and at a plain
mean-of-ranks, moves a top-100 player by 0.3 places on average and 2 at worst.
What actually decides the ordering is how absence is treated, below.

**Absence is not the same as missing data.** A source that ranks 400 players and
leaves someone off has expressed an opinion; a source that only publishes 75
has not. So a player absent from a source is scored as if ranked just past the
end of that list (`depth * CENSOR`) when some other source puts him inside that
depth — the source saw him and passed — and otherwise the source abstains and
casts no vote at all. Getting this wrong in either direction is what moves
players tens of places, which is why it is a rule and not a fudge factor.

**A slot with no row in it is not an absence.** dynatyze's markup omits 7 of its
top 75 positions; the ranks exist on the page, the players behind them do not
reach the scrape. Someone holds those slots, so they are handed to the
best-consensus players the source left out rather than counted as a pass.
`kind='inferred'` marks every vote that came from this, because it is a guess
about a scrape, not something the source said.

**Draft picks are held out.** dynatyze ranks "2027 Early 1st" among the players.
It keeps its slot — so that rank is not offered as a hidden one — but it is not
a player and is not reranked.
"""
import json
import math
import re
from collections import defaultdict

from ..names import normalize
from ..sources.rankings import SOURCES

# Ranks-to-value decay constant and the penalty a source's list-end carries, both
# reasoned about in the module docstring. Retuning either changes stored runs, so
# they are recorded on the run row rather than assumed at read time.
DEFAULT_CURVE = 80.0
DEFAULT_CENSOR = 1.15

# "2027 Early 1st", "2026 2nd" — future picks, which dynatyze ranks inline with
# players. No NBA player's name matches either half of this.
PICK_RE = re.compile(r"^20\d\d\b|\b(?:1st|2nd)\b", re.I)


def value(rank: float, curve: float = DEFAULT_CURVE) -> float:
    """A rank's share of the #1 slot's value, on the decay curve above."""
    return 100.0 * math.exp(-(rank - 1.0) / curve)


def kinds() -> list[str]:
    """The distinct list kinds the registry knows about, e.g. ['dynasty']."""
    return sorted({src.kind for src in SOURCES.values()})


def sources_of_kind(con, kind: str) -> dict[str, int]:
    """
    source -> the ranking_pull_id behind it, for stored sources of this kind.

    Registry order decides *what* is comparable; the database decides what is
    actually there. A source registered but never pulled simply does not appear.
    """
    registered = [name for name, src in SOURCES.items() if src.kind == kind]
    if not registered:
        return {}
    rows = con.execute(
        "SELECT source, max(ranking_pull_id) FROM v_player_rankings "
        f"WHERE source IN ({', '.join('?' * len(registered))}) GROUP BY source",
        registered,
    ).fetchall()
    return {source: pull_id for source, pull_id in rows}


def _consensus(ranks: dict[str, int]) -> float:
    """
    Geometric mean of the ranks a player does have.

    Geometric because it is a claim about position, not value: being #4 and #40
    is a different assertion from being #22 twice, and the geometric mean of
    12.6 says so where the arithmetic 22 does not.
    """
    return math.exp(sum(math.log(r) for r in ranks.values()) / len(ranks))


def _player_keys(con) -> dict[str, str]:
    """
    normalized Yahoo name -> player_key, so a composite row says who it is in the
    league. Same lookup rankings.py does at pull time, redone here because the
    league snapshot may have moved since the ranking pull that stored the row.
    """
    try:
        rows = con.execute("SELECT full_name, player_key FROM v_players").fetchall()
    except Exception:
        return {}  # no league snapshot yet; the composite stands on its own
    return {normalize(name): key for name, key in rows if name and key}


def build(con, kind: str = "dynasty",
          curve: float = DEFAULT_CURVE, censor: float = DEFAULT_CENSOR) -> dict:
    """
    Rerank every player named by any source of `kind`. Read-only; plain dicts.

    Returns the ordering under `players` — one dict per player, `rank` 1..n by
    descending `score` — alongside what produced it: the `sources` that voted
    and the pull behind each, their `depth`, the `hidden` slots found in each,
    and the `picks` held out. Raises when no source of that kind is stored,
    rather than returning an empty ranking that looks like a real one.
    """
    srcs = sources_of_kind(con, kind)
    if not srcs:
        raise RuntimeError(
            f"No {kind} rankings stored. Run `fantasy rankings pull <source>` first."
        )

    rows = con.execute(
        "SELECT source, rank, player_name, player_name_key, team_abbr, age, extra "
        "FROM v_player_rankings "
        f"WHERE source IN ({', '.join('?' * len(srcs))}) AND rank IS NOT NULL",
        list(srcs),
    ).fetchall()

    depth: dict[str, int] = {}
    seen: dict[str, set[int]] = defaultdict(set)
    players: dict[str, dict] = defaultdict(
        lambda: {"ranks": {}, "names": {}, "team_abbr": None, "age": None})
    picks: list[dict] = []

    for source, rank, name, name_key, team, age, _extra in rows:
        depth[source] = max(depth.get(source, 0), rank)
        seen[source].add(rank)          # a pick still occupies its slot
        if PICK_RE.search(name or ""):
            picks.append({"source": source, "rank": rank, "player_name": name})
            continue
        p = players[name_key]
        p["ranks"][source] = rank
        p["names"][source] = name
        p["team_abbr"] = p["team_abbr"] or team
        if p["age"] is None:
            p["age"] = age

    hidden = {s: sorted(set(range(1, depth[s] + 1)) - seen[s]) for s in srcs}

    # Hand each source's empty slots to the players it left out, best consensus
    # first. Ordering by consensus is the only signal available: the slot is a
    # hole in the scrape, so nothing says who is in it but where else he ranks.
    inferred: dict[tuple[str, str], int] = {}
    for source, slots in hidden.items():
        if not slots:
            continue
        claimants = sorted(
            (_consensus(p["ranks"]), key) for key, p in players.items()
            if source not in p["ranks"] and min(p["ranks"].values()) <= depth[source]
        )
        for slot, (_, key) in zip(slots, claimants):
            inferred[(key, source)] = slot

    by_key = _player_keys(con)
    order = sorted(srcs, key=lambda s: -depth[s])

    out = []
    for name_key, p in players.items():
        ranked = p["ranks"]
        best = min(ranked.values())
        votes = {}
        for source in order:
            if source in ranked:
                effective, how = float(ranked[source]), "ranked"
            elif (name_key, source) in inferred:
                effective, how = float(inferred[(name_key, source)]), "inferred"
            elif best <= depth[source]:
                effective, how = depth[source] * censor, "passed"
            else:
                continue                # list never reached him; no opinion to read
            votes[source] = {"rank": ranked.get(source), "effective": effective,
                             "kind": how, "value": value(effective, curve)}

        out.append({
            "player_name": p["names"].get(order[0]) or next(iter(p["names"].values())),
            "player_name_key": name_key,
            "player_key": by_key.get(name_key),
            "team_abbr": p["team_abbr"],
            "age": p["age"],
            "score": sum(v["value"] for v in votes.values()) / len(votes),
            "consensus": _consensus(ranked),
            "n_sources": len(ranked),
            "n_votes": len(votes),
            "spread": max(ranked.values()) - best if len(ranked) > 1 else None,
            "votes": votes,
        })

    out.sort(key=lambda r: (-r["score"], r["player_name"]))
    for i, row in enumerate(out, 1):
        row["rank"] = i

    return {
        "kind": kind,
        "params": {"curve": curve, "censor": censor},
        "sources": srcs,
        "depth": depth,
        "hidden": {s: h for s, h in hidden.items() if h},
        "picks": picks,
        "players": out,
    }


def load(con, kind: str = "dynasty") -> dict:
    """
    The stored composite, newest run of `kind`, in the shape `build` returns.

    This is the read path — `fantasy rankings composite show`, the JSON server, a
    REPL — and it deliberately does not recompute: a stored run is an answer as
    of the pulls named on its run row, and stays comparable to itself.
    """
    run = con.execute(
        "SELECT run_id, computed_at, sources, params, note FROM composite_runs "
        "WHERE kind = ? AND status = 'success' ORDER BY run_id DESC LIMIT 1",
        [kind],
    ).fetchone()
    if not run:
        raise RuntimeError(
            f"No stored {kind} composite. Run `fantasy rankings composite build`."
        )

    run_id, computed_at, sources, params, note = run
    rows = con.execute(
        "SELECT rank, score, player_name, player_name_key, player_key, team_abbr, "
        "age, n_sources, n_votes, consensus, spread, votes "
        "FROM composite_rankings WHERE run_id = ? ORDER BY rank",
        [run_id],
    ).fetchall()

    return {
        "run_id": run_id,
        "computed_at": computed_at,
        "kind": kind,
        "note": note,
        "params": json.loads(params or "{}"),
        "sources": json.loads(sources or "{}"),
        "players": [
            {"rank": r, "score": s, "player_name": n, "player_name_key": nk,
             "player_key": pk, "team_abbr": t, "age": a, "n_sources": ns,
             "n_votes": nv, "consensus": c, "spread": sp,
             "votes": json.loads(v or "{}")}
            for r, s, n, nk, pk, t, a, ns, nv, c, sp, v in rows
        ],
    }
