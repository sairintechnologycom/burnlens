"""Explicit, operator-run cloud schema migrations.

Migrations are intentionally not called from FastAPI startup.  Apply them
before enabling code that reads the additive schema.
"""
