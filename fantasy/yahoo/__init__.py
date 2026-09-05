"""
The Yahoo Fantasy Sports integration, split three ways.

`auth.py` holds the OAuth token, `client.py` makes the requests, and `parse.py`
turns Yahoo's deeply nested, index-keyed JSON into flat rows. The parsers are
pure functions with no network of their own — that split is why they are the
part of the integration that can be tested, and they are where a change in
Yahoo's shape shows up first.
"""
