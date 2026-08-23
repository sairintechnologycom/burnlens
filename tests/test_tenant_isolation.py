"""Cross-workspace isolation guard for every authenticated cloud route.

WHY THIS EXISTS, AND WHY IT DOES NOT LOOK LIKE THE EXISTING CROSS-TENANT TESTS

The cross-tenant assertions we already had (test_phase16_api_keys.py, and the
incidental ones in test_phase09_quota.py / test_ingest_wire_format.py) all take
this shape:

    with patch("...execute_query", AsyncMock(return_value=[])):
        r = await ac.patch(f"/account/api-keys/{some_other_workspaces_key}")
    assert r.status_code == 404

That asserts the handler 404s when the database returns nothing. It cannot fail
if the leak it is named after is present: a handler whose SQL forgot
`AND workspace_id = $n` would, against a real Postgres, get the other tenant's
row back and happily return 200 — but the mock returns `[]` no matter what the
SQL said, so the test passes either way. It is the same vacuous shape as
`test_all_api_v1_routes_mounted_in_server` before e98c58d: an assertion that
was structurally unable to observe the thing it claimed to check.

So this suite asserts one rung lower, on the SQL that was actually issued:

    every query a route sends to a tenant-scoped table must carry a
    workspace predicate bound to the caller's OWN workspace_id, taken
    from the signed JWT and never from client input.

That is the real invariant. `workspace_id` enters the request only via
`verify_token` -> `TokenPayload.workspace_id`; a route that filters on anything
else, or does not filter at all, is a cross-workspace read waiting for two
tenants to share a table.

Because the assertion is on the emitted SQL rather than on a mocked return
value, it fails on the leak whether or not the fixture happens to hand back a
row — which is the whole point.
"""

from __future__ import annotations

import inspect
import re
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from burnlens_cloud.auth import verify_token
from burnlens_cloud.models import TokenPayload

# ---------------------------------------------------------------------------
# Tenant-scoped tables — every table in burnlens_cloud/database.py whose DDL
# declares a workspace_id column. A query touching one of these without binding
# the caller's workspace is the bug this file exists to catch.
#
# Kept as a literal (not derived at runtime) so that ADDING a scoped table is a
# deliberate edit here: a table that silently appears in neither list would be
# swept under the rug by a clever auto-derivation the day someone renames the
# DDL block. test_scoped_table_list_matches_ddl below pins it to the schema.
# ---------------------------------------------------------------------------
TENANT_SCOPED_TABLES = frozenset(
    {
        "alert_events",
        "alert_rules",
        "api_keys",
        "cancellation_surveys",
        "invitations",
        "outcomes",
        "reconciliation_credentials",
        "reconciliation_runs",
        "request_records",
        "waste_findings",
        "workspace_activity",
        "workspace_members",
        "workspace_settings",
        "workspace_usage_cycles",
    }
)

# Tables with no workspace_id column. Global config, or scoped by their own
# identity column (`workspaces.id`, `users.id`) rather than by a foreign key.
UNSCOPED_TABLES = frozenset(
    {
        "auth_tokens",
        "paddle_events",
        "plan_limits",
        "status_checks",
        "used_action_tokens",
        "users",
        "workspaces",
    }
)

# Modules that pull execute_query / execute_insert into their own namespace.
# Patching is per-module because each did `from .database import execute_query`,
# so patching burnlens_cloud.database alone would miss every caller.
# Modules that skip execute_query and run SQL straight off a pooled connection.
POOL_CALLER_MODULES = ("cron_api", "findings_api")

DB_CALLER_MODULES = (
    "actions_api",
    "alerts_api",
    "api_keys_api",
    "auth",
    "billing",
    "dashboard_api",
    "ingest",
    "outcomes_api",
    "plans",
    "reconciliation",
    "settings_api",
    "team_api",
)


# ---------------------------------------------------------------------------
# SQL inspection
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\$(\d+)")

# `workspace_id = $3`, `wm.workspace_id=$1`, `w.id = $2`, `workspace_id IN ($1)`.
_WS_PREDICATE = re.compile(
    r"(?:\b\w+\.)?\b(?:workspace_id|id)\s*(?:=|\bIN\b)\s*\(?\s*\$(\d+)",
    re.IGNORECASE,
)

_TABLE_REF = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+(?:ONLY\s+)?([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)


def tables_touched(sql: str) -> set[str]:
    """Return the known table names referenced by `sql`.

    Deliberately ignores anything not in our two schema lists — CTE aliases,
    subquery aliases and set-returning functions all show up after FROM/JOIN and
    are not tables we can leak across.
    """
    known = TENANT_SCOPED_TABLES | UNSCOPED_TABLES
    return {t.lower() for t in _TABLE_REF.findall(sql) if t.lower() in known}


# `INSERT INTO workspace_activity (workspace_id, user_id, ...) VALUES ($1, $2, ...)`
_INSERT_SHAPE = re.compile(
    r"INSERT\s+INTO\s+(?:ONLY\s+)?[a-z_][a-z0-9_]*\s*\(([^)]*)\)\s*VALUES\s*\(([^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)


def _insert_binds_workspace(sql: str, args: tuple, wanted: str) -> bool | None:
    """Resolve the workspace_id binding of an INSERT by column position.

    An INSERT carries no WHERE clause, so the predicate check below cannot see
    it — but a write is still tenant-scoped, and a route that inserts under
    someone else's workspace_id is a real (if quieter) isolation break than a
    read. Rather than exempt every write, map the workspace_id column to its
    placeholder and check the value bound there.

    Returns None if `sql` is not a column-list INSERT, so the caller can fall
    through to the predicate check (an `INSERT ... SELECT ... WHERE` is scoped
    by its WHERE clause like any read).
    """
    match = _INSERT_SHAPE.search(sql)
    if not match:
        return None
    columns = [c.strip().strip('"').lower() for c in match.group(1).split(",")]
    if "workspace_id" not in columns:
        return None
    values = [v.strip() for v in match.group(2).split(",")]
    position = columns.index("workspace_id")
    if position >= len(values):
        return False
    placeholder = _PLACEHOLDER.search(values[position])
    if not placeholder:
        return False
    idx = int(placeholder.group(1)) - 1
    return 0 <= idx < len(args) and str(args[idx]) == wanted


def binds_workspace(sql: str, args: tuple, workspace_id: str) -> bool:
    """True if `sql` constrains a workspace column to `workspace_id`.

    Checks the BOUND VALUE, not just the presence of the column: a query reading
    `workspace_id = $1` with an id that came from the request body rather than
    the token is exactly the leak, and would pass a text-only check.
    """
    wanted = str(workspace_id)

    inserted = _insert_binds_workspace(sql, args, wanted)
    if inserted is not None:
        return inserted

    for pos in _WS_PREDICATE.findall(sql):
        idx = int(pos) - 1
        if 0 <= idx < len(args) and str(args[idx]) == wanted:
            return True
    return False


class QuerySpy:
    """Records every (sql, args) a route issues and returns an empty result.

    Returning `[]` is safe here precisely because this suite never asserts on
    the returned rows — the verdict is read off the recorded SQL.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def __call__(self, sql, *args, **kwargs):
        self.calls.append((sql, args))
        return []

    async def _fetchrow(self, sql, *args, **kwargs):
        self.calls.append((sql, args))
        return None

    async def _fetchval(self, sql, *args, **kwargs):
        self.calls.append((sql, args))
        return None

    async def _executemany(self, sql, args_list, **kwargs):
        for args in args_list or [()]:
            self.calls.append((sql, tuple(args)))
        return ""

    def fake_pool(self):
        """A stand-in for `get_pool()` whose connection records the same way.

        findings_api and the cron routes bypass execute_query entirely — they
        take `get_pool()` and run SQL on the connection directly. Patching only
        execute_query leaves that whole path unspied, which for a leak hunt
        means the routes most likely to hand-roll SQL are the ones least
        watched.
        """
        conn = AsyncMock()
        conn.fetch = self
        conn.fetchrow = self._fetchrow
        conn.fetchval = self._fetchval
        conn.execute = self._fetchval
        conn.executemany = self._executemany

        # MagicMock, not AsyncMock: `pool.acquire()` must return the async
        # context manager synchronously. An AsyncMock returns a coroutine, and
        # `async with` on it raises before any SQL is recorded.
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool

    def offenders(self, workspace_id: str) -> list[tuple[str, str]]:
        """(table, sql) for each tenant-scoped query missing the caller's id."""
        out = []
        for sql, args in self.calls:
            for table in tables_touched(sql) & TENANT_SCOPED_TABLES:
                if not binds_workspace(sql, args, workspace_id):
                    out.append((table, " ".join(sql.split())[:400]))
        return out

    @property
    def touched_scoped_table(self) -> bool:
        return any(tables_touched(sql) & TENANT_SCOPED_TABLES for sql, _ in self.calls)


# ---------------------------------------------------------------------------
# Route inventory
# ---------------------------------------------------------------------------


def _walk(routes):
    """Yield real routes, descending through fastapi 0.141's _IncludedRouter.

    include_router() leaves lazy `_IncludedRouter` objects in app.routes that
    carry no `.path` and no `.endpoint`, so the usual
    `[r for r in app.routes if hasattr(r, "path")]` walk silently sees zero
    mounted routes. That is what made the Phase 3 mounting test pass vacuously
    before e98c58d; do not reintroduce it here.
    """
    from fastapi.routing import APIRoute

    try:
        from fastapi.routing import _IncludedRouter
    except ImportError:  # pragma: no cover - fastapi < 0.141
        _IncludedRouter = ()

    for route in routes:
        if _IncludedRouter and isinstance(route, _IncludedRouter):
            yield from _walk(route.original_router.routes)
        elif isinstance(route, APIRoute):
            yield route


def _dependency_names(dependant) -> list[str]:
    names = []
    for sub in dependant.dependencies:
        call = sub.call
        names.append(getattr(call, "__name__", type(call).__name__))
        names.extend(_dependency_names(sub))
    return names


def _is_authed(route) -> bool:
    if "verify_token" in _dependency_names(route.dependant):
        return True
    sig = str(inspect.signature(route.endpoint))
    return "verify_token" in sig or "TokenPayload" in sig


def _build_app():
    from burnlens_cloud.main import app

    return app


def authed_routes() -> list[tuple[str, str]]:
    """(method, path) for every authenticated route on the production app."""
    found = []
    for route in _walk(_build_app().routes):
        if not _is_authed(route):
            continue
        for method in sorted(route.methods or []):
            if method in ("HEAD", "OPTIONS"):
                continue
            found.append((method, route.path))
    return sorted(found)


ROUTES = authed_routes()

# Path params get a syntactically valid but foreign value. `{provider}` is an
# enum-ish segment, so it gets a real provider name rather than a UUID.
_PATH_PARAM_VALUES = {"provider": "anthropic"}


def _fill_path(path: str, foreign_id: str) -> str:
    def sub(match: re.Match) -> str:
        name = match.group(1).split(":")[0]
        return _PATH_PARAM_VALUES.get(name, foreign_id)

    return re.sub(r"\{([^}]+)\}", sub, path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _token(workspace_id: UUID, role: str = "owner") -> TokenPayload:
    return TokenPayload(
        workspace_id=workspace_id,
        user_id=uuid4(),
        role=role,
        plan="enterprise",  # widest plan: never 402/403 out before reaching SQL
        iat=int(time.time()),
        exp=int(time.time()) + 86400,
    )


@pytest.fixture
def workspaces() -> tuple[UUID, UUID]:
    """(victim, attacker). The attacker holds the token; the victim owns the data."""
    return uuid4(), uuid4()


# A resource id the attacker does not own, kept DISTINCT from the victim's
# workspace_id. Reusing one uuid for both makes
# test_client_supplied_workspace_id_is_ignored fire on any route that
# legitimately binds its own path parameter (`/runs/{run_id}`), which is a
# self-inflicted failure, not a leak.
FOREIGN_RESOURCE_ID = "11111111-2222-3333-4444-555555555555"


class _Harness:
    def __init__(self, app, client, spy, attacker, victim):
        self.foreign_id = FOREIGN_RESOURCE_ID
        self.app = app
        self.client = client
        self.spy = spy
        self.attacker = attacker
        self.victim = victim


@pytest.fixture
async def harness(workspaces):
    """Production app, authed as the attacker workspace, with every DB call spied.

    `resolve_limits` and the plan/quota lookups are stubbed permissively so that
    a route is never rejected before it reaches the SQL this suite reads. A 402
    or 403 would hide a leak rather than prove its absence.
    """
    victim, attacker = workspaces
    app = _build_app()
    spy = QuerySpy()

    app.dependency_overrides[verify_token] = lambda: _token(attacker)

    patches = []
    for module in DB_CALLER_MODULES:
        target = f"burnlens_cloud.{module}"
        for fn in ("execute_query", "execute_insert"):
            try:
                patches.append(patch(f"{target}.{fn}", spy))
            except AttributeError:  # pragma: no cover - fn not imported there
                continue

    permissive_limits = {
        "plan": "enterprise",
        "max_requests_per_month": 10**9,
        "max_api_keys": 10**6,
        "max_members": 10**6,
        "retention_days": 3650,
        "routing_overrides": None,
        "limit_overrides": None,
    }
    patches.append(
        patch("burnlens_cloud.auth.resolve_limits", AsyncMock(return_value=permissive_limits))
    )
    for module in POOL_CALLER_MODULES:
        patches.append(
            patch(f"burnlens_cloud.{module}.get_pool", lambda: spy.fake_pool())
        )

    started = []
    try:
        for p in patches:
            try:
                p.start()
                started.append(p)
            except (AttributeError, ModuleNotFoundError):
                continue
        # raise_app_exceptions=False: the spy returns empty results, so handlers
        # that index into a RETURNING row raise IndexError. That is a fixture
        # artefact, not a leak, and the SQL issued before the raise is still
        # what this suite reads. Letting it surface as a 500 keeps the sweep on
        # the question it is asking. test_sweep_actually_reaches_sql is the
        # backstop against routes that crash BEFORE any SQL runs.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield _Harness(app, ac, spy, attacker, victim)
    finally:
        for p in started:
            p.stop()
        app.dependency_overrides.pop(verify_token, None)


async def _call(harness: _Harness, method: str, path: str, **kwargs):
    request = getattr(harness.client, method.lower())
    # Every mutating cloud route requires the CSRF header (see GEMINI.md);
    # without it the request 403s before any SQL runs and proves nothing.
    headers = {"X-Requested-With": "XMLHttpRequest"}
    headers.update(kwargs.pop("headers", {}))
    if method in ("POST", "PUT", "PATCH"):
        kwargs.setdefault("json", {})
    return await request(path, headers=headers, **kwargs)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", ROUTES, ids=[f"{m} {p}" for m, p in ROUTES])
async def test_route_scopes_every_tenant_query_to_the_caller(harness, method, path):
    """No authed route may query a tenant-scoped table without its own workspace_id.

    The request is made as the attacker workspace, and every path parameter is
    filled with an id the attacker does not own. Whatever SQL results, each
    statement that reaches a tenant-scoped table must bind the ATTACKER's
    workspace_id — i.e. the route scoped the read to the token's workspace and
    the foreign id in the URL could at most select nothing.
    """
    await _call(harness, method, _fill_path(path, harness.foreign_id))

    offenders = harness.spy.offenders(str(harness.attacker))
    assert not offenders, (
        f"{method} {path} queried tenant-scoped table(s) without binding the "
        f"caller's workspace_id ({harness.attacker}):\n"
        + "\n".join(f"  [{table}] {sql}" for table, sql in offenders)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [r for r in ROUTES if r[0] == "GET"],
    ids=[f"{m} {p}" for m, p in ROUTES if m == "GET"],
)
async def test_client_supplied_workspace_id_is_ignored(harness, method, path):
    """A workspace_id in the query string must never reach the SQL.

    Server-side scoping is only worth anything if the client cannot talk the
    route out of it. This is the parameter-pollution form of the leak: a handler
    that reads `request.query_params["workspace_id"]` as a convenience, or a
    Pydantic model that accepts the field, hands any authenticated user every
    other tenant's data for the price of one query parameter.
    """
    await _call(
        harness,
        method,
        _fill_path(path, harness.foreign_id),
        params={"workspace_id": str(harness.victim)},
    )

    leaked = [
        " ".join(sql.split())[:400]
        for sql, args in harness.spy.calls
        if any(str(a) == str(harness.victim) for a in args)
    ]
    assert not leaked, (
        f"{method} {path} bound a client-supplied workspace_id ({harness.victim}) "
        "into its SQL:\n" + "\n".join(f"  {sql}" for sql in leaked)
    )


# ---------------------------------------------------------------------------
# Guards on the guard
# ---------------------------------------------------------------------------


def test_route_inventory_is_not_empty():
    """The sweep is only worth anything if it found routes to sweep.

    fastapi 0.141 already broke one route walk in this repo by making
    include_router() store lazy `_IncludedRouter` objects (see _walk). If that
    representation changes again, the parametrised tests above would collapse to
    zero cases and report green having checked nothing. This is the tripwire.
    """
    assert len(ROUTES) >= 50, (
        f"expected the cloud app to expose 50+ authed routes, found {len(ROUTES)}. "
        "Route enumeration is probably broken, not the app."
    )


@pytest.mark.asyncio
async def test_sweep_actually_reaches_sql(harness):
    """At least some routes must issue tenant-scoped SQL under the harness.

    If a dependency change made every route 401/403/422 before touching the
    database, every assertion above would pass on an empty query log. This test
    fails in that case, so the suite cannot quietly stop testing anything.
    """
    reached = 0
    for method, path in ROUTES:
        harness.spy.calls.clear()
        await _call(harness, method, _fill_path(path, harness.foreign_id))
        if harness.spy.touched_scoped_table:
            reached += 1

    assert reached >= 15, (
        f"only {reached} of {len(ROUTES)} authed routes reached a tenant-scoped "
        "query; the harness is probably short-circuiting before the DB layer."
    )


def test_scoped_table_list_matches_ddl():
    """TENANT_SCOPED_TABLES must stay in step with the schema in database.py.

    A new table with a workspace_id column that nobody adds here would be
    invisible to the sweep — the leak class would grow while the suite kept
    reporting green.
    """
    import pathlib

    lines = pathlib.Path("burnlens_cloud/database.py").read_text().splitlines()
    starts = [
        (i, re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", line).group(1))
        for i, line in enumerate(lines)
        if "CREATE TABLE IF NOT EXISTS" in line
    ]

    scoped, unscoped = set(), set()
    for idx, (line_no, name) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        body = "\n".join(lines[line_no:end]).split('"""')[0]
        (scoped if re.search(r"\bworkspace_id\b", body) else unscoped).add(name)

    assert scoped == set(TENANT_SCOPED_TABLES), (
        "tenant-scoped tables drifted from the DDL.\n"
        f"  in DDL, not in list: {sorted(scoped - set(TENANT_SCOPED_TABLES))}\n"
        f"  in list, not in DDL: {sorted(set(TENANT_SCOPED_TABLES) - scoped)}"
    )
    assert unscoped == set(UNSCOPED_TABLES), (
        "unscoped tables drifted from the DDL.\n"
        f"  in DDL, not in list: {sorted(unscoped - set(UNSCOPED_TABLES))}\n"
        f"  in list, not in DDL: {sorted(set(UNSCOPED_TABLES) - unscoped)}"
    )
