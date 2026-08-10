"""Economics-graph Phase E: reconcile BurnLens's number against the provider's bill.

Nobody trusts a cost tool until it survives the comparison with the invoice.
Once a day we ask each provider's billing API what it charged, sum what
BurnLens computed from proxied traffic over the same UTC day, and store the
drift. The dashboard shows the result per provider, so every number above it —
including cost-per-outcome — carries evidence.

Drift is a diagnosis, not a failure. Traffic that never went through the proxy,
pricing that lags a provider's change, and rounding all produce legitimate
drift, and BurnLens counting *less* than the bill is the normal direction.

Credentials here are read-only billing keys, encrypted at rest with the same
Fernet key as the OTEL exporter credentials (OTEL_ENCRYPTION_KEY). They are
never returned by any endpoint.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Awaitable, Callable, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path

from .auth import require_role, verify_token, TokenPayload
from .database import execute_query
from .email import send_ops_alert
from .encryption import get_encryption_manager
from .models import ProviderReconciliation, ReconciliationCredentialRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reconciliation"])

# Drift above this fires an operator alert and flips the dashboard badge.
# 2% is tight enough to catch a pricing-table bug and loose enough to survive
# rounding and a handful of non-proxied calls.
DRIFT_ALERT_THRESHOLD_PCT = 2.0

_ANTHROPIC_COST_URL = "https://api.anthropic.com/v1/organizations/cost_report"
_OPENAI_COST_URL = "https://api.openai.com/v1/organization/costs"

# One day at daily granularity is a single bucket, so pagination should never
# kick in — the cap only stops a misbehaving API from looping forever.
_MAX_PAGES = 10


class ProviderCostError(Exception):
    """The provider's billing API refused or failed the request."""


def _check(resp: httpx.Response, provider: str) -> None:
    if resp.status_code >= 400:
        raise ProviderCostError(
            f"{provider} cost API returned {resp.status_code}: {resp.text[:200]}"
        )


async def _anthropic_day_cost(api_key: str, day: date) -> float:
    """Anthropic org cost for one UTC day, in USD."""
    headers = {"anthropic-version": "2023-06-01"}
    # Admin API keys authenticate with x-api-key; OAuth tokens with a bearer.
    # Match on `sk-ant-admin` specifically: OAuth tokens are `sk-ant-oat01-...`,
    # so a bare `sk-ant-` test sends them as x-api-key and Anthropic 401s.
    if api_key.startswith("sk-ant-admin"):
        headers["x-api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    # Decimal, not float: these are money strings and the sum is compared
    # against a NUMERIC column.
    total_minor = Decimal(0)
    page: Optional[str] = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(_MAX_PAGES):
            params = {
                "starting_at": f"{day.isoformat()}T00:00:00Z",
                "ending_at": f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z",
                "bucket_width": "1d",
            }
            if page:
                params["page"] = page
            resp = await client.get(_ANTHROPIC_COST_URL, params=params, headers=headers)
            _check(resp, "anthropic")
            body = resp.json()
            for bucket in body.get("data") or []:
                for item in bucket.get("results") or []:
                    total_minor += Decimal(str(item.get("amount") or "0"))
            page = body.get("next_page") if body.get("has_more") else None
            if not page:
                break

    # `amount` is in the currency's minor units — "123.45" USD is $1.23.
    # Treating it as dollars would overstate the bill 100x and make every
    # workspace look catastrophically under-counted.
    return float(total_minor / 100)


async def _openai_day_cost(api_key: str, day: date) -> float:
    """OpenAI org cost for one UTC day, in USD."""
    start = int(datetime.combine(day, time.min, tzinfo=timezone.utc).timestamp())
    total = 0.0
    page: Optional[str] = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(_MAX_PAGES):
            params: dict = {
                "start_time": start,
                "end_time": start + 86_400,
                "bucket_width": "1d",
            }
            if page:
                params["page"] = page
            resp = await client.get(
                _OPENAI_COST_URL,
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            _check(resp, "openai")
            body = resp.json()
            for bucket in body.get("data") or []:
                for item in bucket.get("results") or []:
                    # Already dollars here, unlike Anthropic's minor units.
                    total += float((item.get("amount") or {}).get("value") or 0.0)
            page = body.get("next_page") if body.get("has_more") else None
            if not page:
                break
    return total


# Providers with a usable cost API. A provider absent here simply cannot be
# reconciled — the dashboard says so rather than implying agreement.
PROVIDERS: dict[str, Callable[[str, date], Awaitable[float]]] = {
    "anthropic": _anthropic_day_cost,
    "openai": _openai_day_cost,
}


def compute_drift_pct(provider_cost: float, burnlens_cost: float) -> Optional[float]:
    """Signed percent BurnLens differs from the provider. None if nothing to divide by."""
    if provider_cost <= 0:
        return None
    return (burnlens_cost - provider_cost) / provider_cost * 100


def classify(
    drift_pct: Optional[float],
    burnlens_cost: Optional[float],
    threshold: float = DRIFT_ALERT_THRESHOLD_PCT,
) -> str:
    """Badge state for one provider's most recent run."""
    if drift_pct is None:
        # Provider billed nothing. Agreement only if BurnLens also saw nothing —
        # spend we counted that the provider did not bill is real drift, it just
        # has no percentage.
        return "reconciled" if not burnlens_cost else "drifted"
    return "reconciled" if abs(drift_pct) <= threshold else "drifted"


async def _burnlens_day_cost(workspace_id, provider: str, day: date) -> float:
    rows = await execute_query(
        """
        SELECT COALESCE(SUM(cost_usd), 0) AS cost
        FROM request_records
        WHERE workspace_id = $1 AND provider = $2 AND ts >= $3 AND ts < $4
        """,
        workspace_id,
        provider,
        datetime.combine(day, time.min, tzinfo=timezone.utc),
        datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc),
    )
    return float(rows[0]["cost"]) if rows else 0.0


async def reconcile_all_workspaces(day: Optional[date] = None) -> dict:
    """Reconcile every stored credential for one UTC day. Defaults to yesterday.

    Yesterday, not today: provider billing lags, so a same-day comparison
    reports drift that is only reporting delay.
    """
    if day is None:
        day = datetime.now(timezone.utc).date() - timedelta(days=1)

    creds = await execute_query(
        "SELECT workspace_id, provider, api_key_encrypted FROM reconciliation_credentials"
    )
    if not creds:
        return {"checked": 0, "failed": 0, "alerted": 0}

    manager = get_encryption_manager()
    checked = failed = alerted = 0

    for cred in creds:
        provider = cred["provider"]
        fetch = PROVIDERS.get(provider)
        if fetch is None:
            continue
        try:
            provider_cost = await fetch(manager.decrypt(cred["api_key_encrypted"]), day)
        except Exception as exc:
            # One bad credential must not stop the rest of the run.
            failed += 1
            logger.warning(
                "reconcile: %s failed for workspace %s: %s",
                provider, cred["workspace_id"], exc,
            )
            continue

        burnlens_cost = await _burnlens_day_cost(cred["workspace_id"], provider, day)
        drift = compute_drift_pct(provider_cost, burnlens_cost)

        await execute_query(
            """
            INSERT INTO reconciliation_runs
                (workspace_id, provider, day, provider_cost_usd, burnlens_cost_usd, drift_pct)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (workspace_id, provider, day) DO UPDATE
            SET provider_cost_usd = EXCLUDED.provider_cost_usd,
                burnlens_cost_usd = EXCLUDED.burnlens_cost_usd,
                drift_pct         = EXCLUDED.drift_pct,
                computed_at       = NOW()
            """,
            cred["workspace_id"], provider, day,
            Decimal(str(round(provider_cost, 6))),
            Decimal(str(round(burnlens_cost, 6))),
            drift,
        )
        checked += 1

        if classify(drift, burnlens_cost) == "drifted":
            alerted += 1
            await send_ops_alert(
                f"BurnLens reconciliation drift: {provider}",
                f"Workspace {cred['workspace_id']} on {day.isoformat()}\n"
                f"Provider billed ${provider_cost:.4f}, BurnLens computed "
                f"${burnlens_cost:.4f} (drift "
                f"{'n/a' if drift is None else f'{drift:+.2f}%'}, "
                f"threshold {DRIFT_ALERT_THRESHOLD_PCT}%).\n"
                "Usual causes: traffic not routed through the proxy, a stale "
                "pricing entry, or an unpriced model.",
            )

    logger.info(
        "reconcile: day=%s checked=%d failed=%d alerted=%d",
        day, checked, failed, alerted,
    )
    return {"checked": checked, "failed": failed, "alerted": alerted}


def _manager_or_503():
    try:
        return get_encryption_manager()
    except ValueError:
        # OTEL_ENCRYPTION_KEY unset. Storing a plaintext billing key instead is
        # not an option, so refuse loudly rather than fail open.
        raise HTTPException(
            status_code=503,
            detail="Credential storage is not configured on this deployment",
        )


@router.put("/settings/reconciliation/{provider}")
async def put_reconciliation_credential(
    body: ReconciliationCredentialRequest,
    provider: str = Path(..., description="Provider key, e.g. anthropic or openai"),
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """Store a provider billing-API key. Owner only; the key is never read back."""
    await require_role("owner", token)
    if provider not in PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"No cost API for '{provider}'. Supported: {', '.join(sorted(PROVIDERS))}",
        )
    manager = _manager_or_503()

    # Prove the key works before storing it. A key that 401s would leave the
    # badge stuck on "unreconciled" with no explanation anywhere.
    day = datetime.now(timezone.utc).date() - timedelta(days=1)
    try:
        await PROVIDERS[provider](body.api_key, day)
    except ProviderCostError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach {provider}: {exc}"
        )

    await execute_query(
        """
        INSERT INTO reconciliation_credentials (workspace_id, provider, api_key_encrypted)
        VALUES ($1, $2, $3)
        ON CONFLICT (workspace_id, provider) DO UPDATE
        SET api_key_encrypted = EXCLUDED.api_key_encrypted, updated_at = NOW()
        """,
        str(token.workspace_id), provider, manager.encrypt(body.api_key),
    )
    return {"provider": provider, "status": "connected"}


@router.delete("/settings/reconciliation/{provider}")
async def delete_reconciliation_credential(
    provider: str = Path(...),
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """Forget a provider billing key. Past runs stay — they are history, not config."""
    await require_role("owner", token)
    await execute_query(
        "DELETE FROM reconciliation_credentials WHERE workspace_id = $1 AND provider = $2",
        str(token.workspace_id), provider,
    )
    return {"provider": provider, "status": "removed"}


_STATUS_SQL = """
SELECT c.provider, r.day, r.provider_cost_usd, r.burnlens_cost_usd,
       r.drift_pct, r.computed_at
FROM reconciliation_credentials c
LEFT JOIN LATERAL (
    SELECT day, provider_cost_usd, burnlens_cost_usd, drift_pct, computed_at
    FROM reconciliation_runs r
    WHERE r.workspace_id = c.workspace_id AND r.provider = c.provider
    ORDER BY r.day DESC
    LIMIT 1
) r ON TRUE
WHERE c.workspace_id = $1
ORDER BY c.provider
"""


@router.get("/api/v1/reconciliation", response_model=list[ProviderReconciliation])
async def reconciliation_status(
    token: TokenPayload = Depends(verify_token),
) -> list[ProviderReconciliation]:
    """Per-provider drift for the dashboard badge. Empty list = nothing configured."""
    await require_role("viewer", token)
    rows = await execute_query(_STATUS_SQL, str(token.workspace_id))

    out: list[ProviderReconciliation] = []
    for r in rows:
        if r["day"] is None:
            # Credential stored, no run yet — the cron has not come round.
            out.append(
                ProviderReconciliation(provider=r["provider"], status="unreconciled")
            )
            continue
        drift = float(r["drift_pct"]) if r["drift_pct"] is not None else None
        burnlens_cost = float(r["burnlens_cost_usd"])
        out.append(
            ProviderReconciliation(
                provider=r["provider"],
                status=classify(drift, burnlens_cost),
                day=r["day"],
                provider_cost_usd=float(r["provider_cost_usd"]),
                burnlens_cost_usd=burnlens_cost,
                drift_pct=drift,
                computed_at=r["computed_at"],
            )
        )
    return out
