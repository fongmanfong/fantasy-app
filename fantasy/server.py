"""
Local HTTP server behind `fantasy view`.

Standard library only — the point of this project is a CLI, and a read-only
JSON shell over DuckDB does not justify a web framework.
"""
import json
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import duckdb

from . import query
from .store import db

APP_HTML = Path(__file__).parent / "templates" / "app.html"


class Handler(BaseHTTPRequestHandler):
    """
    Serves the single-page app and a read-only JSON API over `query.py`.

    `GET /` returns the app; `/api/meta`, `/api/roster?team=`,
    `/api/free-agents`, `/api/standings`, `/api/compare?a=&b=` and
    `/api/keepers` return the corresponding `query` call. All but `/api/keepers`
    take an optional `?period=` (default "season"). Anything that goes wrong
    comes back as `{"error": ...}` with a 400, since every failure here is a bad
    request, an empty snapshot, or a board that has not been loaded yet.
    """

    def __init__(self, *args, con=None, lock=None, **kw):
        self.con, self.lock = con, lock
        super().__init__(*args, **kw)

    # Keep the terminal for the CLI's own output.
    def log_message(self, *args):
        pass

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status: int = 200):
        self._send(status, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        period = params.get("period", "season")

        if url.path in ("/", "/index.html"):
            self._send(200, APP_HTML.read_bytes(), "text/html; charset=utf-8")
            return

        if not url.path.startswith("/api/"):
            self._json({"error": "not found"}, 404)
            return

        try:
            # One connection shared across threads; DuckDB wants calls serialised.
            with self.lock:
                if url.path == "/api/meta":
                    out = query.meta(self.con)
                elif url.path == "/api/roster":
                    team = params.get("team")
                    if not team:
                        raise ValueError("roster needs a ?team= key")
                    out = query.roster(self.con, team, period)
                elif url.path == "/api/free-agents":
                    out = query.free_agents(self.con, period)
                elif url.path == "/api/standings":
                    out = query.standings(self.con, period)
                elif url.path == "/api/keepers":
                    out = query.keeper_board(self.con)
                elif url.path == "/api/compare":
                    a, b = params.get("a"), params.get("b")
                    if not (a and b):
                        raise ValueError("compare needs ?a= and ?b= team keys")
                    out = query.compare(self.con, a, b, period)
                else:
                    self._json({"error": f"unknown endpoint {url.path}"}, 404)
                    return
        except Exception as exc:
            self._json({"error": str(exc)}, 400)
            return

        self._json(out)


def serve(port: int = 8777):
    """
    Open the snapshot read-only and serve until interrupted.

    Read-only means other `fantasy` commands, and a duckdb shell, can still open
    the same file while the interface is running.
    """
    if not db.config.DB_PATH.exists():
        raise db.NoDatabase(
            f"No database at {db.config.DB_PATH} yet. Run `fantasy pull` first.")

    con = duckdb.connect(str(db.config.DB_PATH), read_only=True)
    handler = partial(Handler, con=con, lock=threading.Lock())
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    return httpd, con
