"""FastAPI router for provider signature endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from burnlens.api.schemas import SignatureCreateRequest, SignatureResponse, signature_to_response
from burnlens.storage.database import insert_provider_signature
from burnlens.storage.models import ProviderSignature
from burnlens.storage.queries import get_provider_signatures

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/signatures", response_model=list[SignatureResponse])
async def list_provider_signatures(
    request: Request,
    provider: Optional[str] = Query(default=None, description="Filter by provider name"),
) -> list[SignatureResponse]:
    """List all known provider signatures, optionally filtered by provider name.

    Returns both seeded (built-in) signatures and any custom signatures created
    via POST /providers/signatures.
    """
    db_path: str = request.app.state.db_path
    sigs = await get_provider_signatures(db_path, provider=provider)
    return [signature_to_response(s) for s in sigs]


@router.post("/signatures", response_model=SignatureResponse, status_code=201)
async def create_provider_signature(
    request: Request,
    body: SignatureCreateRequest,
) -> JSONResponse:
    """Create a custom provider signature for detecting a new AI provider.

    The signature is persisted to the database and immediately available for
    use by the detection engine. If a signature with the same provider name
    already exists (INSERT OR IGNORE), the existing record is returned.

    Returns 201 with the created SignatureResponse on success.
    """
    db_path: str = request.app.state.db_path

    sig = ProviderSignature(
        provider=body.provider,
        endpoint_pattern=body.endpoint_pattern,
        header_signature=body.header_signature,
        model_field_path=body.model_field_path,
    )

    new_id = await insert_provider_signature(db_path, sig)

    if new_id == 0:
        # Provider already exists — fetch and return existing record
        existing = await get_provider_signatures(db_path, provider=body.provider)
        if existing:
            return JSONResponse(
                content=signature_to_response(existing[0]).model_dump(),
                status_code=201,
            )

    # Fetch the newly created record by id
    all_sigs = await get_provider_signatures(db_path, provider=body.provider)
    created = next((s for s in all_sigs if s.id == new_id), None)
    if created is None:
        # Fallback: return the first matching provider signature
        created = all_sigs[0] if all_sigs else sig
        if created.id is None:
            created.id = new_id  # type: ignore[assignment]

    return JSONResponse(
        content=signature_to_response(created).model_dump(),
        status_code=201,
    )
