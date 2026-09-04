"""Shared HTTP fetch for ranking sources.

Kept separate from each site's parse module so a parser stays pure and testable
against a saved fixture, the same split as yahoo/parse.py vs yahoo/client.py.
"""
import requests

TIMEOUT = 20

# A ranking site rendered server-side (this is a scrape, not an API) can refuse a
# request with no browser-shaped User-Agent.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}


def get(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text
