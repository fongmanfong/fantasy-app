"""Computes a composite ranking from the stored sources and appends it to DuckDB.

Shaped like rankings.py, minus the network: the method lives in
analysis/composite.py and returns plain dicts, and this owns the connection, the
run row and the writing. It is the only writer that reads the database it writes
to — a composite is derived from ranking pulls already stored, so a run is
recorded with the pull ids behind it and can be read back long after those pulls
have been superseded.
"""
import json
import logging
from dataclasses import dataclass, field

from .analysis import composite as model
from .store import db

logger = logging.getLogger(__name__)


@dataclass
class CompositeRunResult:
    """What one composite run folded together, and what it found doing it."""
    run_id: int
    kind: str
    sources: dict[str, int] = field(default_factory=dict)  # source -> ranking_pull_id
    players: int = 0
    picks: list[dict] = field(default_factory=list)        # held out, not reranked
    hidden: dict[str, list[int]] = field(default_factory=dict)
    inferred: int = 0       # votes filled from a source's empty slots
    passed: int = 0         # votes from a source that saw a player and left him off
    error: str | None = None

    @property
    def status(self) -> str:
        return "error" if self.error else "success"


def run(kind: str = "dynasty", curve: float = model.DEFAULT_CURVE,
        censor: float = model.DEFAULT_CENSOR) -> CompositeRunResult:
    """
    Rerank every player any source of `kind` names, and store the result.

    Opens a **writable** connection, so it cannot run alongside a pull. Appends:
    the previous run stays queryable by run_id, and only the newest successful
    one is what `v_composite_rankings` resolves to.
    """
    with db.connect() as con:
        db.init_schema(con)     # the composite tables postdate older databases

        try:
            result = model.build(con, kind=kind, curve=curve, censor=censor)
        except Exception as exc:
            logger.warning("composite build failed: %s", exc)
            raise

        run_id = db.new_composite_run(con, kind, result["sources"], result["params"])
        out = CompositeRunResult(
            run_id=run_id, kind=kind,
            sources=result["sources"], picks=result["picks"], hidden=result["hidden"],
        )

        try:
            rows = [
                {**{k: p[k] for k in (
                    "rank", "score", "player_name", "player_name_key", "player_key",
                    "team_abbr", "age", "n_sources", "n_votes", "consensus", "spread")},
                 "votes": json.dumps(p["votes"])}
                for p in result["players"]
            ]
            db.insert_composite_rows(con, rows, run_id)
        except Exception as exc:
            logger.warning("composite run %s failed: %s", run_id, exc)
            out.error = str(exc)
            db.complete_composite_run(con, run_id, out.status, out.error)
            return out

        out.players = len(rows)
        for player in result["players"]:
            for vote in player["votes"].values():
                if vote["kind"] == "inferred":
                    out.inferred += 1
                elif vote["kind"] == "passed":
                    out.passed += 1

        note = (f"{out.players} players from {len(out.sources)} sources; "
                f"{out.passed} censored votes, {out.inferred} inferred")
        db.complete_composite_run(con, run_id, out.status, note)

    return out
