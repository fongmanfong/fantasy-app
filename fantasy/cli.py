"""`fantasy` — pull a Yahoo Fantasy NBA league into DuckDB and query it."""
import logging
import webbrowser
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.table import Table

from . import config, pull as pull_mod, server as server_mod
from .analysis import matchup as matchup_mod, projection, waiver as waiver_mod
from .store import db
from .store.db import NoDatabase
from .yahoo import auth
from .yahoo.client import STAT_PERIODS, YahooClient

app = typer.Typer(add_completion=False, help=__doc__, no_args_is_help=True)
auth_app = typer.Typer(help="Authenticate with Yahoo.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")

console = Console()
err = Console(stderr=True)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")


def fail(message: str) -> None:
    err.print(f"[red]error:[/red] {message}")
    raise typer.Exit(1)


def _cell(value) -> str:
    return "" if value is None else str(value)


def render(rows: list[tuple], headers: list[str], title: str | None = None) -> None:
    """
    Print a result set.

    Rich shrinks columns to fit the terminal, which turns a many-column result (a
    PIVOT over every stat category, say) into unreadable one-character slivers.
    In that case fall back to tab-separated output, which stays legible and pipes
    cleanly into other tools. With few columns rich wraps long cells acceptably,
    so keep the table there even when it overflows.
    """
    body = [[_cell(v) for v in row] for row in rows]
    widths = [
        max([len(str(h))] + [len(r[i]) for r in body]) if body else len(str(h))
        for i, h in enumerate(headers)
    ]
    needed = sum(widths) + 3 * len(headers) + 1

    if needed > console.width and len(headers) > 8:
        if title:
            console.print(f"[bold]{title}[/bold]")
        console.print("\t".join(str(h) for h in headers), highlight=False)
        for row in body:
            console.print("\t".join(row), highlight=False)
        console.print(
            f"[dim]{len(headers)} columns — shown tab-separated, too wide to tabulate[/dim]"
        )
        return

    table = Table(title=title, header_style="bold", show_lines=False)
    for header in headers:
        table.add_column(str(header))
    for row in body:
        table.add_row(*row)
    console.print(table)


# --- auth ---------------------------------------------------------------

@auth_app.command("login")
def auth_login():
    """Authorize this machine against your Yahoo account."""
    try:
        url = auth.get_auth_url()
    except RuntimeError as exc:
        fail(str(exc))

    console.print("\n[bold]1.[/bold] Open this URL and approve access:\n")
    console.print(f"   [cyan]{url}[/cyan]\n")
    console.print(
        "[bold]2.[/bold] Yahoo redirects to [dim]https://localhost[/dim], which will not load.\n"
        "   That is expected — copy the full URL out of the address bar.\n"
    )

    pasted = typer.prompt("Paste the redirect URL (or just the code)")
    try:
        token = auth.exchange_code(pasted)
    except Exception as exc:
        fail(f"token exchange failed: {exc}")

    expires = auth.token_expires_at(token)
    console.print(f"\n[green]Authenticated.[/green] Token saved to {config.TOKEN_PATH}")
    if expires:
        console.print(f"Access token expires {expires:%Y-%m-%d %H:%M UTC} (auto-refreshed).")


@auth_app.command("status")
def auth_status():
    """Show credential and token state."""
    has_creds = bool(config.client_id() and config.client_secret())
    token = auth.load_token()
    expires = auth.token_expires_at(token)

    rows = [
        ("client credentials", "set" if has_creds else "MISSING (see .env.example)"),
        ("token file", str(config.TOKEN_PATH) if token else "none — run `fantasy auth login`"),
        ("access token", "expired (will auto-refresh)" if token and auth.is_expired(token) else ("valid" if token else "-")),
        ("expires at", f"{expires:%Y-%m-%d %H:%M UTC}" if expires else "-"),
        ("database", str(config.DB_PATH) + ("" if config.DB_PATH.exists() else "  (not created yet)")),
    ]
    render(rows, ["", ""], title="Yahoo auth")

    if not (has_creds and token):
        raise typer.Exit(1)

    try:
        leagues = YahooClient().my_leagues()
        console.print(f"[green]Connected.[/green] {len(leagues)} NBA league(s) visible.")
    except Exception as exc:
        fail(f"credentials present but the API call failed: {exc}")


@auth_app.command("logout")
def auth_logout():
    """Delete the stored token."""
    auth.clear_token()
    console.print("Token cleared.")


# --- data ---------------------------------------------------------------

@app.command("leagues")
def leagues_cmd():
    """List the NBA leagues on your Yahoo account."""
    try:
        leagues = YahooClient().my_leagues()
    except Exception as exc:
        fail(str(exc))

    if not leagues:
        console.print("No NBA leagues found on this account.")
        return

    render(
        [(lg["league_key"], lg["name"], lg["season"], lg["num_teams"], lg["scoring_type"]) for lg in leagues],
        ["league_key", "name", "season", "teams", "scoring"],
        title="Your leagues",
    )


@app.command("pull")
def pull_cmd(
    league_key: str = typer.Argument(None, help="League key or id. Omitted: your only league."),
    periods: str = typer.Option(
        ",".join(pull_mod.DEFAULT_PERIODS), "--periods",
        help=f"Stat splits to fetch. Options: {', '.join(STAT_PERIODS)}",
    ),
    skip_stats: bool = typer.Option(False, "--skip-stats", help="Skip player stats (much faster)."),
    fa_limit: int = typer.Option(None, "--fa-limit", help="Cap the free-agent pool. Default: all."),
):
    """Snapshot a league's current state into DuckDB."""
    period_list = [p.strip() for p in periods.split(",") if p.strip()]

    with console.status("[cyan]starting[/cyan]") as status:
        try:
            result = pull_mod.run(
                league_key=league_key,
                periods=period_list,
                skip_stats=skip_stats,
                fa_limit=fa_limit,
                on_step=lambda msg: status.update(f"[cyan]{msg}[/cyan]"),
            )
        except Exception as exc:
            fail(str(exc))

    console.print(
        f"\n[green]Pull #{result.pull_id}[/green] {result.league_key} "
        f"— [bold]{result.status}[/bold]"
    )
    render(sorted(result.counts.items()), ["table", "rows inserted"])

    if result.errors:
        err.print(f"[yellow]{len(result.errors)} step(s) failed:[/yellow]")
        for e in result.errors:
            err.print(f"  - {e}")


@app.command("pulls")
def pulls_cmd(limit: int = typer.Option(20, "--limit")):
    """List past pulls."""
    try:
        with db.connect(read_only=True) as con:
            rows = con.execute(
                "SELECT pull_id, league_key, pulled_at, status, note "
                "FROM pulls ORDER BY pull_id DESC LIMIT ?", [limit]
            ).fetchall()
    except NoDatabase as exc:
        fail(str(exc))
    render(
        [(p, lk, f"{t:%Y-%m-%d %H:%M}", s, (n or "")[:60]) for p, lk, t, s, n in rows],
        ["pull", "league", "pulled_at (UTC)", "status", "note"],
        title="Pulls",
    )


@app.command("tables")
def tables_cmd():
    """Show every table and view with its row count."""
    try:
        with db.connect(read_only=True) as con:
            rows = [(name, db.row_count(con, name)) for name in db.table_names(con)]
    except NoDatabase as exc:
        fail(str(exc))
    render(rows, ["name", "rows"], title=str(config.DB_PATH))


@app.command("view")
def view_cmd(
    port: int = typer.Option(8777, "--port", help="Port to serve on."),
    open_browser: bool = typer.Option(True, "--open/--no-open",
                                      help="Open the interface in your browser."),
):
    """Open the league interface: rosters, standings, free agents, compare."""
    try:
        httpd, con = server_mod.serve(port)
    except NoDatabase as exc:
        fail(str(exc))
    except OSError as exc:
        fail(f"could not bind port {port}: {exc}. Try `fantasy view --port 8778`.")

    url = f"http://127.0.0.1:{port}/"
    console.print(f"[green]League interface[/green] running at [bold]{url}[/bold]")
    console.print("[dim]The snapshot is opened read-only, so other fantasy "
                  "commands still work. Ctrl-C to stop.[/dim]")
    if open_browser:
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        console.print("\nStopped.")
    finally:
        httpd.server_close()
        con.close()


# --- analysis -----------------------------------------------------------

def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:5.1f}%"


def _bar(p: float, width: int = 12) -> str:
    filled = int(round(p * width))
    colour = "green" if p >= 0.55 else ("red" if p <= 0.45 else "yellow")
    return f"[{colour}]{'#' * filled}[/{colour}][dim]{'.' * (width - filled)}[/dim]"


def _fmt(cat: dict, value) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}" if cat.get("rate") else f"{value:.1f}"


@app.command("matchup")
def matchup_cmd(
    opponent: str = typer.Argument(None, help="Opponent: team key, id, or part of a name. Omitted: the whole league."),
    team: str = typer.Option(None, "--team", help="Team to analyse. Default: yours."),
    sims: int = typer.Option(10000, "--sims", help="Simulated weeks."),
    games: float = typer.Option(projection.GAMES_PER_WEEK, "--games",
                                help="Average NBA games per team per week."),
    periods: str = typer.Option(None, "--periods", help="Stat windows to blend. Default: all present."),
    seed: int = typer.Option(0, "--seed", help="Random seed. Use different values to check stability."),
):
    """Category-by-category win probabilities against another team."""
    window = [p.strip() for p in periods.split(",")] if periods else None
    try:
        with db.connect(read_only=True) as con:
            if opponent is None:
                report = matchup_mod.versus_field(con, team, window, sims, seed, games)
                _render_field(report)
            else:
                report = matchup_mod.head_to_head(con, team, opponent, window, sims, seed, games)
                _render_matchup(report)
    except (NoDatabase, RuntimeError) as exc:
        fail(str(exc))


def _render_matchup(r: dict) -> None:
    a, b = r["a"], r["b"]
    console.print(f"\n[bold]{a['name']}[/bold] vs [bold]{b['name']}[/bold]  "
                  f"[dim]{r['sims']:,} simulated weeks, {r['games_per_week']} games/team[/dim]\n")

    rows = []
    for cat in r["categories"]:
        rows.append((
            cat["label"],
            _fmt(cat, cat["a_mean"]), _fmt(cat, cat["b_mean"]),
            _pct(cat["p_win"]), _bar(cat["p_win"]),
        ))
    render(rows, ["cat", a["name"][:18], b["name"][:18], "win", ""])

    console.print(
        f"\nExpected score [bold]{r['expected_cats_won']:.1f}[/bold] of {len(r['categories'])} "
        f"categories   |   matchup [green]{_pct(r['p_win']).strip()} win[/green], "
        f"{_pct(r['p_tie']).strip()} tie, {_pct(r['p_loss']).strip()} loss"
    )
    spread = sorted(r["score_distribution"].items())
    console.print("[dim]categories won: " +
                  "  ".join(f"{k}:{100 * v:.0f}%" for k, v in spread if v >= 0.02) +
                  "[/dim]")


def _render_field(r: dict) -> None:
    console.print(f"\n[bold]{r['a']['name']}[/bold] against the league  "
                  f"[dim]{r['sims']:,} simulated weeks each[/dim]\n")
    render(
        [(c["label"], _pct(c["p_win"]), _bar(c["p_win"])) for c in r["categories"]],
        ["cat", "win", ""], title="Average category odds",
    )
    render(
        [(o["name"], f"{o['expected_cats_won']:.1f}", _pct(o["p_win"]), _bar(o["p_win"]))
         for o in r["opponents"]],
        ["opponent", "cats", "win", ""], title="Toughest matchups first",
    )
    console.print(f"\nAverage week: [bold]{r['expected_cats_won']:.1f}[/bold] categories, "
                  f"[bold]{_pct(r['p_win']).strip()}[/bold] to win a random matchup")


@app.command("waivers")
def waivers_cmd(
    versus: str = typer.Option(None, "--vs", help="Optimise against one opponent. Default: the whole league."),
    team: str = typer.Option(None, "--team", help="Team to improve. Default: yours."),
    top: int = typer.Option(12, "--top", help="Moves to show."),
    drops: int = typer.Option(6, "--drops", help="How many of your players to consider dropping."),
    sims: int = typer.Option(4000, "--sims", help="Simulated weeks."),
    games: float = typer.Option(projection.GAMES_PER_WEEK, "--games",
                                help="Average NBA games per team per week."),
    min_gp: float = typer.Option(5.0, "--min-gp", help="Ignore free agents below this many games."),
    periods: str = typer.Option(None, "--periods", help="Stat windows to blend. Default: all present."),
    seed: int = typer.Option(0, "--seed", help="Random seed."),
    by_player: bool = typer.Option(False, "--by-player",
                                   help="One row per free agent, with their best drop."),
):
    """Simulate free-agent pickups and rank them by the odds they buy."""
    window = [p.strip() for p in periods.split(",")] if periods else None
    try:
        with console.status("[cyan]simulating[/cyan]"):
            with db.connect(read_only=True) as con:
                r = waiver_mod.add_drop(con, team, versus, window, sims, seed,
                                        games, drops, top, min_gp)
    except (NoDatabase, RuntimeError) as exc:
        fail(str(exc))

    target = "the league" if len(r["opponents"]) > 1 else r["opponents"][0]["name"]
    base = r["baseline"]
    console.print(
        f"\n[bold]{r['team']['name']}[/bold] vs {target}  "
        f"[dim]{r['sims']:,} weeks, {r['considered']['free_agents']} free agents, "
        f"{r['considered']['pairs']} legal swaps[/dim]"
    )
    console.print(f"Now: [bold]{base['expected_cats_won']:.2f}[/bold] categories, "
                  f"[bold]{_pct(base['p_win']).strip()}[/bold] to win a week\n")

    moves = r["best_by_player"] if by_player else r["moves"]
    if not moves:
        console.print("[yellow]No legal improving move found.[/yellow]")
        return

    rows = []
    for m in moves:
        gains = sorted(m["categories"].items(), key=lambda kv: -kv[1])
        labels = {c["key"]: c["label"] for c in r["categories"]}
        helps = ", ".join(f"{labels[k]} +{100 * v:.0f}" for k, v in gains[:3] if v > 0.01)
        hurts = ", ".join(f"{labels[k]} {100 * v:.0f}" for k, v in gains[-2:] if v < -0.01)
        sign = "+" if m["delta_cats"] >= 0 else ""
        rows.append((
            f"{m['add']['name']} ({'/'.join(m['add']['positions'])})",
            m["drop"]["name"],
            f"{sign}{m['delta_cats']:.2f}",
            f"{sign}{100 * m['delta_p_win']:.1f}pp",
            helps or "-",
            hurts or "-",
        ))
    render(rows, ["add", "drop", "cats", "win%", "gains (pp)", "costs (pp)"])
    console.print("[dim]cats = change in expected categories won per week; "
                  "win% = change in the odds of winning the matchup[/dim]")

    render([(d["name"], "/".join(d["positions"]), d["slot"] or "", f"{d['cost']:.2f}")
            for d in r["drop_candidates"]],
           ["droppable", "pos", "slot", "cost (cats)"],
           title="Cheapest to drop")


@app.command("sql")
def sql_cmd(
    query: str = typer.Argument(..., help="SQL to run against the DuckDB file."),
    limit: int = typer.Option(50, "--limit", help="Max rows to print. 0 for all."),
):
    """Run ad-hoc SQL."""
    try:
        with db.connect(read_only=True) as con:
            try:
                cursor = con.execute(query)
            except Exception as exc:
                fail(str(exc))
            headers = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
    except NoDatabase as exc:
        fail(str(exc))

    shown = rows if limit == 0 else rows[:limit]
    render(shown, headers)
    if len(shown) < len(rows):
        console.print(f"[dim]{len(shown)} of {len(rows)} rows — raise with --limit 0[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
