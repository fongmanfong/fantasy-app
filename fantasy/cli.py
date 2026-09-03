"""`fantasy` — pull a Yahoo Fantasy NBA league into DuckDB and query it."""
import logging
import sys
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.table import Table

from . import config, pull as pull_mod
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

    Rich shrinks columns to fit the terminal, which turns a wide result (a PIVOT
    over every stat category, say) into unreadable one-character slivers. Past a
    width the terminal cannot hold, fall back to tab-separated output, which stays
    legible and pipes cleanly into other tools.
    """
    body = [[_cell(v) for v in row] for row in rows]
    widths = [
        max([len(str(h))] + [len(r[i]) for r in body]) if body else len(str(h))
        for i, h in enumerate(headers)
    ]
    needed = sum(widths) + 3 * len(headers) + 1

    if needed > console.width:
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
