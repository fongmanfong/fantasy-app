"""
Yahoo OAuth 2.0 for a CLI.

Yahoo "Installed Application" apps redirect to https://localhost, which nothing is
listening on — so this is an out-of-band flow: we print the consent URL, you approve
in a browser, then paste the URL you land on back into the terminal.

Tokens are persisted to ~/.fantasy/token.json (mode 600), never to the database.
"""
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from requests_oauthlib import OAuth2Session

from .. import config

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
REDIRECT_URI = "https://localhost"
# Send no scope by default. Yahoo rejects the whole authorization request with
# `invalid_scope` if the app registration lacks any scope named -- including
# "fspt-r" itself -- so naming one buys nothing and breaks apps that would
# otherwise work. Omitting it lets the app's registered permissions decide,
# which is what the long-standing Yahoo Fantasy clients do.
# Override with YAHOO_SCOPE if you need a specific scope.
_scope_env = os.getenv("YAHOO_SCOPE", "")
SCOPE = _scope_env.split() if _scope_env.strip() else None


def _write_private(path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def load_token() -> dict | None:
    """
    The stored OAuth token, or None if there is none to read.

    A corrupt or unreadable file reads as "no token" rather than raising: the
    recovery is `fantasy auth login` either way.
    """
    if not config.TOKEN_PATH.exists():
        return None
    try:
        return json.loads(config.TOKEN_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_token(token: dict) -> None:
    """Write the token to ~/.fantasy/token.json, mode 600, replacing atomically."""
    _write_private(config.TOKEN_PATH, dict(token))


def clear_token() -> None:
    """Forget this machine's authorisation — the token and the login state."""
    config.TOKEN_PATH.unlink(missing_ok=True)
    config.STATE_PATH.unlink(missing_ok=True)


def token_expires_at(token: dict | None = None) -> datetime | None:
    """When the access token lapses, in UTC, or None if that is not recorded."""
    token = token or load_token()
    if not token or not token.get("expires_at"):
        return None
    return datetime.fromtimestamp(float(token["expires_at"]), tz=timezone.utc)


def is_expired(token: dict | None = None, skew: int = 60) -> bool:
    """
    Whether the token needs refreshing, `skew` seconds early so a request does
    not lapse in flight. A missing token or a missing expiry counts as expired.
    """
    token = token or load_token()
    if not token:
        return True
    expires_at = token.get("expires_at")
    if not expires_at:
        return True
    return float(expires_at) - skew <= time.time()


def get_auth_url() -> str:
    """Build the consent URL and stash the CSRF state for the exchange."""
    cid, _ = config.require_credentials()
    oauth = OAuth2Session(cid, redirect_uri=REDIRECT_URI, scope=SCOPE)
    auth_url, state = oauth.authorization_url(AUTH_URL)
    _write_private(config.STATE_PATH, {"state": state})
    return auth_url


def extract_code(pasted: str) -> str:
    """Accept either a bare code or the full https://localhost/?code=...&state=... URL."""
    pasted = pasted.strip()
    if "code=" not in pasted:
        return pasted

    query = urlparse(pasted).query or pasted.split("?", 1)[-1]
    params = parse_qs(query)

    expected = _expected_state()
    returned = params.get("state", [None])[0]
    if expected and returned and returned != expected:
        raise ValueError(
            "OAuth state mismatch — the pasted URL did not come from the login "
            "URL just printed. Run `fantasy auth login` again."
        )

    code = params.get("code", [None])[0]
    if not code:
        raise ValueError("Could not find a `code` parameter in the pasted URL.")
    return code


def _expected_state() -> str | None:
    if not config.STATE_PATH.exists():
        return None
    try:
        return json.loads(config.STATE_PATH.read_text()).get("state")
    except (json.JSONDecodeError, OSError):
        return None


def exchange_code(pasted: str) -> dict:
    """Trade an authorization code for a token and persist it."""
    cid, secret = config.require_credentials()
    code = extract_code(pasted)

    oauth = OAuth2Session(cid, redirect_uri=REDIRECT_URI)
    token = oauth.fetch_token(TOKEN_URL, code=code, client_secret=secret)
    save_token(token)
    config.STATE_PATH.unlink(missing_ok=True)
    return token


def session() -> OAuth2Session:
    """An OAuth2Session that transparently refreshes and persists the token."""
    cid, secret = config.require_credentials()
    token = load_token()
    if not token or not token.get("access_token"):
        raise RuntimeError("Not authenticated with Yahoo. Run `fantasy auth login` first.")

    return OAuth2Session(
        cid,
        token=token,
        auto_refresh_url=TOKEN_URL,
        auto_refresh_kwargs={"client_id": cid, "client_secret": secret},
        token_updater=save_token,
    )


def refresh_now() -> dict:
    """Force a token refresh up front, so a stale token fails here and not mid-pull."""
    cid, secret = config.require_credentials()
    token = load_token()
    if not token or not token.get("refresh_token"):
        raise RuntimeError("No refresh token stored. Run `fantasy auth login` first.")

    oauth = OAuth2Session(cid, token=token)
    new_token = oauth.refresh_token(
        TOKEN_URL,
        refresh_token=token["refresh_token"],
        client_id=cid,
        client_secret=secret,
    )
    # Yahoo does not always echo the refresh token back; keep the one we have.
    new_token.setdefault("refresh_token", token["refresh_token"])
    save_token(new_token)
    return new_token
