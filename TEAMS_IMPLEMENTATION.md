# Teams Plan Implementation — BurnLens Cloud

## Summary

Implemented Teams plan features for BurnLens Cloud backend, enabling multi-user workspace collaboration with role-based access control (RBAC), invitation system, and activity logging.

## What Was Implemented

### Phase 1: Database Schema & Foundation ✅
- **4 new PostgreSQL tables**:
  - `users` — Email + OAuth identifiers (google_id, github_id)
  - `workspace_members` — Membership tracking with roles (owner/admin/viewer)
  - `invitations` — Pending invites with 48-hour expiry tokens
  - `workspace_activity` — Audit log of admin actions

- **Model Updates**:
  - Extended `TokenPayload` with `user_id` and `role` fields
  - Added Pydantic schemas for team endpoints (InvitationRequest, InvitationResponse, etc.)

- **Configuration**:
  - Seat limits per plan: free=1, cloud=3, teams=10, enterprise=999
  - SSO environment variables (Google, GitHub)
  - Email configuration (SendGrid)
  - Invitation expiry: 48 hours

- **Email Service**:
  - Created `email.py` with SendGrid integration
  - Async non-blocking invitation email sending

### Phase 2: User & Membership Management ✅
- **Team Management API** (`team_api.py`):
  - `GET /team/members` — List workspace members
  - `DELETE /team/members/{user_id}` — Remove member (admin+)
  - `PATCH /team/members/{user_id}` — Change role (admin+)
  - `GET /team/activity` — Audit log (admin+)

- **Authentication Enhancements** (auth.py):
  - `upsert_user()` — Create or update user by email/OAuth IDs
  - `ensure_workspace_member()` — Add user to workspace with role
  - `auto_migrate_user_for_workspace()` — Transparent migration for existing workspaces
  - Updated `encode_jwt()` to include user_id and role
  - Updated login/signup flows to create user records

### Phase 3: Invitation System ✅
- **POST /team/invite** — Send invitations (admin+ required)
  - Validates team plan requirement
  - Enforces seat limits
  - Sends email with invitation link
  - Logs activity

- **GET /invite/{token}** — Accept invitations
  - Handles unauthenticated users (redirects to signup)
  - Validates token expiry (48 hours)
  - Auto-adds user to workspace_members
  - Logs activity

### Phase 4: RBAC Enforcement ✅
- **Role Hierarchy**: viewer (0) < admin (1) < owner (2)
- **Permissions**:
  - **viewer**: GET dashboard endpoints only
  - **admin**: GET + settings/budget configuration
  - **owner**: All + billing + workspace deletion

- **Dashboard API Updates** (dashboard_api.py):
  - Added `require_role()` helper for permission checking
  - Updated all GET endpoints to require "viewer" role
  - Returns 403 with error details on insufficient permissions

### Phase 5: Workspace Migration ✅
- Existing single-user workspaces auto-migrate on first login
- Creates user record for owner_email
- Adds to workspace_members with "owner" role
- Transparent to existing users

### Testing ✅
- Created `test_teams.py` with comprehensive test suite:
  - Invitation creation and validation
  - Seat limit enforcement
  - Role-based access control
  - Member management
  - Activity logging

## Files Added
- `burnlens_cloud/team_api.py` — Team management API (330 lines)
- `burnlens_cloud/email.py` — Email service (85 lines)
- `tests/test_teams.py` — Team functionality tests (250 lines)

## Files Modified
- `burnlens_cloud/database.py` — Added 4 table schemas + indexes
- `burnlens_cloud/models.py` — Extended TokenPayload, added team models
- `burnlens_cloud/config.py` — Added seat limits, SSO vars, email config
- `burnlens_cloud/auth.py` — User/member management, auto-migration, updated JWT encoding
- `burnlens_cloud/dashboard_api.py` — Added RBAC enforcement
- `burnlens_cloud/main.py` — Registered team_api router
- `pyproject.toml` — Added sendgrid, google-auth-oauthlib, requests dependencies

## Key Features

### Invitation System
- Email-based invitations with 48-hour expiry
- Secure token-based acceptance flow
- Automatic user creation on signup via invite link
- Activity logging for all invitations

### Role-Based Access Control
- 3-tier role system: owner, admin, viewer
- Transparent enforcement on dashboard endpoints
- Prevents unauthorized access with 403 errors
- Prevents removal of last owner

### Seat Limit Enforcement
- Enforced during invitation creation
- Plan-specific limits (free=1, teams=10)
- Returns 422 error with upgrade prompt when exceeded

### Auto-Migration
- Existing workspaces transparently add user records
- Owner email becomes the first user
- Happens on first login (API key login)
- No manual migration script needed

### Activity Logging
- All admin actions logged to `workspace_activity` table
- Actions tracked: invite_sent, member_joined, member_removed, role_changed
- Available via `/team/activity` endpoint (admin+ only)

## Not Yet Implemented

### Phase 4: Google & GitHub SSO
OAuth flows for seamless onboarding are designed but not yet implemented. They can be added in a future release:
- `GET /auth/google` — Google OAuth redirect
- `GET /auth/google/callback` — Google OAuth callback
- `GET /auth/github` — GitHub OAuth redirect  
- `GET /auth/github/callback` — GitHub OAuth callback

See `/Users/bhushan/.claude/plans/hazy-watching-lantern.md` for SSO implementation details.

## Configuration

### Environment Variables Required

```
# Email (SendGrid)
SENDGRID_API_KEY=...
SENDGRID_FROM_EMAIL=noreply@burnlens.app
BURNLENS_FRONTEND_URL=https://burnlens.app

# Optional (for future SSO):
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://api.burnlens.app/auth/google/callback
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GITHUB_REDIRECT_URI=https://api.burnlens.app/auth/github/callback
```

## Database Schema

All new tables follow PostgreSQL best practices:
- UUID primary keys with `gen_random_uuid()`
- Referential integrity with `ON DELETE CASCADE`
- Appropriate indexes for query performance
- JSONB for flexible audit log details
- Timestamptz for UTC time handling

## API Contract

### Authentication
All team endpoints require JWT token in Authorization header:
```
Authorization: Bearer {jwt_token}
```

### Role Checks
Insufficient role returns 403:
```json
{
  "detail": {
    "error": "insufficient_role",
    "required": "admin",
    "current": "viewer"
  }
}
```

### Seat Limit Enforcement
Exceeding seat limit returns 422:
```json
{
  "detail": {
    "error": "seat_limit_reached",
    "limit": 10,
    "upgrade_url": "https://burnlens.app/upgrade"
  }
}
```

## Next Steps

1. **Deploy to Staging**: Test the Teams flow end-to-end
2. **Frontend Integration**: Create /team dashboard UI for member management
3. **SSO Implementation**: Add Google/GitHub OAuth flows (Phase 4)
4. **Email Templates**: Customize invitation emails with branding
5. **Activity Dashboard**: Build audit log UI for compliance/transparency
6. **Performance**: Monitor database performance and add caching if needed

## Testing

Run teams tests:
```bash
pytest tests/test_teams.py -v
```

All tests use mocked database operations (no real DB required).

## Notes

- All database operations are asynchronous (asyncpg)
- Email sending is non-blocking (fire-and-forget)
- Invitation tokens are 32-char hex strings (same format as API keys)
- Activity logging failures don't fail requests (resilient design)
- Viewer role prevents all sensitive operations while allowing full read access
