"""Guard: every workspaces column that resolve_limits() reads must have DDL.

resolve_limits() is LANGUAGE SQL, so Postgres parses its body at CREATE FUNCTION
time. A column referenced there but never created makes init_db() raise
UndefinedColumnError on any FRESH database — existing deployments keep working
because they already carry the column, so the break is invisible in production
and only bites self-hosters, new staging environments, and restore-from-scratch.

That is exactly what b59ca88 did: it edited the `limit_overrides` migration
block in place to create `routing_overrides` instead, deleting the only DDL for
`limit_overrides`. No DB connection needed — this reads the source.
"""

import pathlib
import re

SRC = pathlib.Path("burnlens_cloud/database.py").read_text()


def _resolve_limits_body() -> str:
    start = SRC.index("CREATE OR REPLACE FUNCTION resolve_limits")
    end = SRC.index("$$", SRC.index("AS $$", start) + 5)
    return SRC[start:end]


def test_resolve_limits_columns_have_ddl():
    body = _resolve_limits_body()
    referenced = set(re.findall(r"\bw\.([a-z_]+)", body))
    assert "limit_overrides" in referenced, "guard is looking at the wrong function body"

    create_table = SRC[SRC.index("CREATE TABLE IF NOT EXISTS workspaces") :][:2000]

    missing = [
        col
        for col in sorted(referenced)
        if not re.search(rf"^\s+{col}\s+\w", create_table, re.M)
        and f"ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS {col} " not in SRC
        and f"ALTER TABLE workspaces ADD COLUMN {col} " not in SRC
    ]
    assert not missing, (
        f"resolve_limits() reads workspaces column(s) {missing} that init_db() never "
        f"creates — a fresh database will fail at CREATE FUNCTION resolve_limits"
    )
