"""Model-level tests for Phase 16 API key management.

Covers (per 16-01 PLAN):
- ApiKeyCreateRequest.name max_length raised to 128 (D-09).
- ApiKey gains optional last_used_at: Optional[datetime] field (D-05).
- ApiKeyUpdateRequest exists with required name field, min_length=1, max_length=128 (D-09/D-10).
"""

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# ApiKeyCreateRequest — D-09 (max_length raised 64 → 128)
# ---------------------------------------------------------------------------

def test_create_request_accepts_128_char_name():
    from burnlens_cloud.models import ApiKeyCreateRequest

    ApiKeyCreateRequest(name="x" * 128)


def test_create_request_rejects_129_char_name():
    from burnlens_cloud.models import ApiKeyCreateRequest

    with pytest.raises(ValidationError):
        ApiKeyCreateRequest(name="x" * 129)


def test_create_request_name_still_optional():
    """Backwards compat: name remains Optional (server defaults to 'Primary')."""
    from burnlens_cloud.models import ApiKeyCreateRequest

    req = ApiKeyCreateRequest()
    assert req.name is None


# ---------------------------------------------------------------------------
# ApiKey — D-05 (last_used_at: Optional[datetime] = None)
# ---------------------------------------------------------------------------

def test_apikey_constructs_without_last_used_at():
    from burnlens_cloud.models import ApiKey

    key = ApiKey(
        id=uuid4(),
        name="Primary",
        last4="abcd",
        created_at=datetime.utcnow(),
    )
    assert key.last_used_at is None


def test_apikey_accepts_last_used_at():
    from burnlens_cloud.models import ApiKey

    now = datetime.utcnow()
    key = ApiKey(
        id=uuid4(),
        name="Primary",
        last4="abcd",
        created_at=now,
        last_used_at=now,
    )
    assert key.last_used_at == now


def test_apikey_field_last_used_at_is_declared():
    """Regression-guard: ensure the field name is exactly `last_used_at`."""
    from burnlens_cloud.models import ApiKey

    assert "last_used_at" in ApiKey.model_fields


# ---------------------------------------------------------------------------
# ApiKeyUpdateRequest — D-09/D-10 (new class, required name field)
# ---------------------------------------------------------------------------

def test_update_request_class_exists():
    from burnlens_cloud import models

    assert hasattr(models, "ApiKeyUpdateRequest"), \
        "ApiKeyUpdateRequest must be exported from burnlens_cloud.models"


def test_update_request_accepts_valid_name():
    from burnlens_cloud.models import ApiKeyUpdateRequest

    req = ApiKeyUpdateRequest(name="hello")
    assert req.name == "hello"


def test_update_request_accepts_128_char_name():
    from burnlens_cloud.models import ApiKeyUpdateRequest

    ApiKeyUpdateRequest(name="x" * 128)


def test_update_request_rejects_empty_name():
    from burnlens_cloud.models import ApiKeyUpdateRequest

    with pytest.raises(ValidationError):
        ApiKeyUpdateRequest(name="")


def test_update_request_rejects_missing_name():
    """name is required (no default) — single-field PATCH, passing None is meaningless."""
    from burnlens_cloud.models import ApiKeyUpdateRequest

    with pytest.raises(ValidationError):
        ApiKeyUpdateRequest()  # type: ignore[call-arg]


def test_update_request_rejects_129_char_name():
    from burnlens_cloud.models import ApiKeyUpdateRequest

    with pytest.raises(ValidationError):
        ApiKeyUpdateRequest(name="x" * 129)


def test_update_request_required_fields_include_name():
    from burnlens_cloud.models import ApiKeyUpdateRequest

    schema = ApiKeyUpdateRequest.model_json_schema()
    assert "name" in schema.get("required", [])
