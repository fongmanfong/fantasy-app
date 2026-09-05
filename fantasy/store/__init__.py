"""
The DuckDB store: `db.py` for access, `schema.sql` for the shape.

Append-only by design. Nothing is ever UPDATEd or DELETEd except a pull row's
own status, so every snapshot stays on disk and the `v_*` views resolve to the
newest successful pull of each kind.
"""
