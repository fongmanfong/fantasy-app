"""Paths and environment configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent

# DuckDB file holding every pull. Override with FANTASY_DB.
DB_PATH = Path(os.getenv("FANTASY_DB", REPO_ROOT / "data" / "fantasy.duckdb"))

# OAuth tokens live outside the database — see README. Override with FANTASY_HOME.
CONFIG_DIR = Path(os.getenv("FANTASY_HOME", Path.home() / ".fantasy"))
TOKEN_PATH = CONFIG_DIR / "token.json"
STATE_PATH = CONFIG_DIR / "state.json"


def client_id() -> str | None:
    return os.getenv("YAHOO_CLIENT_ID")


def client_secret() -> str | None:
    return os.getenv("YAHOO_CLIENT_SECRET")


def require_credentials() -> tuple[str, str]:
    cid, secret = client_id(), client_secret()
    if not cid or not secret:
        raise RuntimeError(
            "YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET are not set. "
            "Copy .env.example to .env and fill them in."
        )
    return cid, secret
