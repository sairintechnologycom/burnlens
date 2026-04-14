"""Audit logging and compliance endpoints."""

import csv
import io
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response

from ..auth import verify_token, require_role
from ..database import get_db
from ..models import AuditLogResponse, AuditLogEntryExtended, TokenPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["compliance"])


@router.get("/audit-log")
async def get_audit_log(
    token: TokenPayload = Depends(verify_token),
    days: int = 365,
    limit: int = 100,
    offset: int = 0,
) -> AuditLogResponse:
    """
    Retrieve audit log for workspace (enterprise plan only).

    Query params:
        - days: Number of days to look back (default: 365, max: 365)
        - limit: Records per page (default: 100, max: 1000)
        - offset: Pagination offset (default: 0)

    Auth: admin+ and enterprise plan only
    """
    require_role("admin", token)

    # Check if enterprise plan
    if token.plan != "enterprise":
        raise HTTPException(
            status_code=403, detail="Audit log available for enterprise plan only"
        )

    # Clamp parameters
    days = min(days, 365)
    limit = min(limit, 1000)
    offset = max(offset, 0)

    try:
        db = await get_db()

        # Fetch total count
        count_result = await db.fetchval(
            """
            SELECT COUNT(*) FROM workspace_activity
            WHERE workspace_id = $1 AND created_at > NOW() - INTERVAL '1 day' * $2
            """,
            token.workspace_id,
            days,
        )
        total = count_result or 0

        # Fetch paginated entries with user info
        rows = await db.fetch(
            """
            SELECT
                wa.id,
                wa.action,
                wa.detail,
                wa.created_at,
                wa.ip_address,
                wa.user_agent,
                wa.api_key_last4,
                u.email as user_email,
                u.name as user_name
            FROM workspace_activity wa
            LEFT JOIN users u ON wa.user_id = u.id
            WHERE wa.workspace_id = $1 AND wa.created_at > NOW() - INTERVAL '1 day' * $2
            ORDER BY wa.created_at DESC
            LIMIT $3 OFFSET $4
            """,
            token.workspace_id,
            days,
            limit,
            offset,
        )

        # Convert to response model
        entries = []
        for row in rows:
            user_email = row.get("user_email") or "unknown"
            if row.get("user_name"):
                user_email = f"{row['user_name']} <{user_email}>"

            entries.append(
                AuditLogEntryExtended(
                    id=row["id"],
                    user=user_email,
                    action=row["action"],
                    detail=row["detail"] or {},
                    created_at=row["created_at"],
                    ip_address=row.get("ip_address"),
                    user_agent=row.get("user_agent"),
                    api_key_last4=row.get("api_key_last4"),
                )
            )

        return AuditLogResponse(
            entries=entries,
            total=total,
            limit=limit,
            offset=offset,
        )

    except Exception as e:
        logger.error(f"Failed to fetch audit log: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch audit log")


@router.get("/audit-log/export")
async def export_audit_log_csv(
    token: TokenPayload = Depends(verify_token),
    days: int = 365,
) -> Response:
    """
    Export audit log as CSV (enterprise plan only).

    Query params:
        - days: Number of days to look back (default: 365, max: 365)

    Auth: admin+ and enterprise plan only
    """
    require_role("admin", token)

    # Check if enterprise plan
    if token.plan != "enterprise":
        raise HTTPException(
            status_code=403,
            detail="Audit log export available for enterprise plan only",
        )

    # Clamp days
    days = min(days, 365)

    try:
        db = await get_db()

        # Fetch all entries for the period (no pagination for export)
        rows = await db.fetch(
            """
            SELECT
                wa.id,
                wa.action,
                wa.detail,
                wa.created_at,
                wa.ip_address,
                wa.user_agent,
                wa.api_key_last4,
                u.email as user_email,
                u.name as user_name
            FROM workspace_activity wa
            LEFT JOIN users u ON wa.user_id = u.id
            WHERE wa.workspace_id = $1 AND wa.created_at > NOW() - INTERVAL '1 day' * $2
            ORDER BY wa.created_at DESC
            """,
            token.workspace_id,
            days,
        )

        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "Timestamp",
            "User",
            "Action",
            "Details",
            "IP Address",
            "User Agent",
            "API Key (last 4)",
        ])

        # Write rows
        for row in rows:
            user_email = row.get("user_email") or "unknown"
            if row.get("user_name"):
                user_email = f"{row['user_name']} <{user_email}>"

            detail_str = ""
            if row.get("detail"):
                # Flatten detail dict to readable string
                detail_str = ", ".join(
                    f"{k}={v}" for k, v in row["detail"].items()
                )

            writer.writerow([
                row["created_at"].isoformat(),
                user_email,
                row["action"],
                detail_str,
                row.get("ip_address") or "",
                row.get("user_agent") or "",
                row.get("api_key_last4") or "",
            ])

        # Return as CSV response
        csv_content = output.getvalue()
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=audit-log-{datetime.utcnow().strftime('%Y-%m-%d')}.csv"
            },
        )

    except Exception as e:
        logger.error(f"Failed to export audit log: {e}")
        raise HTTPException(status_code=500, detail="Failed to export audit log")
