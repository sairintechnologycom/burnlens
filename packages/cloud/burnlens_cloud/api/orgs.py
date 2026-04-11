"""Organization registration and profile endpoints."""

import hashlib
import secrets

import resend
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from burnlens_cloud.api.auth import get_current_org
from burnlens_cloud.config import settings
from burnlens_cloud.db.engine import get_db
from burnlens_cloud.db.models import Organization

router = APIRouter(prefix="/api/v1/orgs", tags=["orgs"])


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr


class RegisterResponse(BaseModel):
    api_key: str
    org_id: str


class OrgProfile(BaseModel):
    org_id: str
    name: str
    tier: str
    api_key_prefix: str
    subscription_status: str | None
    created_at: str


def _slugify(name: str) -> str:
    """Turn an org name into a URL-safe slug."""
    slug = name.lower().strip()
    slug = "".join(c if c.isalnum() or c == " " else "" for c in slug)
    slug = "-".join(slug.split())
    return slug or "org"


@router.post("/register", response_model=RegisterResponse)
async def register_org(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Register a new organization and return a one-time API key."""
    api_key = f"bl_live_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    slug_base = _slugify(body.name)
    slug = f"{slug_base}-{secrets.token_hex(4)}"

    org = Organization(
        name=body.name,
        slug=slug,
        api_key_hash=key_hash,
        tier="free",
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)

    # Send welcome email (skip if using placeholder key)
    if settings.resend_api_key and not settings.resend_api_key.startswith("re_test_"):
        try:
            resend.api_key = settings.resend_api_key
            resend.Emails.send(
                {
                    "from": "BurnLens <noreply@burnlens.dev>",
                    "to": body.email,
                    "subject": "Welcome to BurnLens",
                    "html": (
                        f"<p>Hi {body.name},</p>"
                        "<p>Your BurnLens account is ready. "
                        "Your API key was shown once at registration — "
                        "keep it safe.</p>"
                        "<p>— The BurnLens Team</p>"
                    ),
                }
            )
        except Exception:
            pass  # Fail open — email is non-critical

    return RegisterResponse(api_key=api_key, org_id=str(org.id))


@router.get("/me", response_model=OrgProfile)
async def get_org_profile(
    org: Organization = Depends(get_current_org),
) -> OrgProfile:
    """Return the authenticated organization's profile."""
    return OrgProfile(
        org_id=str(org.id),
        name=org.name,
        tier=org.tier,
        api_key_prefix=org.api_key_hash[:12] + "...",
        subscription_status=org.subscription_status,
        created_at=org.created_at.isoformat(),
    )
