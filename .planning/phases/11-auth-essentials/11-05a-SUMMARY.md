---
phase: 11-auth-essentials
plan: "05a"
subsystem: frontend
tags: [auth, email-verification, useAuth, setup-page, forgot-password, localStorage]

# Dependency graph
requires:
  - 11-03b (backend /auth/reset-password endpoint)
provides:
  - frontend/src/lib/hooks/useAuth.ts::AuthSession.emailVerified
  - frontend/src/app/setup/page.tsx::burnlens_email_verified localStorage persistence
  - frontend/src/app/setup/page.tsx::Forgot password? inline flow
affects:
  - 11-05b (BillingStatusBanner email verification extension reads session.emailVerified)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Grandfathered null → true: burnlens_email_verified missing in localStorage treated as verified"
    - "Fail-open API response: data.email_verified ?? true fallback for legacy backend responses"
    - "Inline toggle pattern: showForgotPw state drives form reveal/hide without route change"

key-files:
  created: []
  modified:
    - frontend/src/lib/hooks/useAuth.ts
    - frontend/src/app/setup/page.tsx

key-decisions:
  - "emailVerified stored as string 'true'/'false' in localStorage (Web Storage only supports strings); parsed back with === 'true' comparison"
  - "storeSession() extended with optional email_verified param rather than adding inline setItem calls in handleLogin/handleRegister — single point of truth for session persistence"
  - "handleForgotSubmit uses BASE_URL (not API_BASE) to match setup/page.tsx's existing fetch convention"

requirements-completed: [AUTH-01, AUTH-06]

# Metrics
duration: "6min"
completed: "2026-05-02"
---

# Phase 11 Plan 05a: emailVerified in useAuth + Forgot password flow on setup page Summary

**emailVerified boolean added to AuthSession with localStorage persistence; setup/page.tsx stores email_verified from login/signup responses and shows inline Forgot password? form calling POST /auth/reset-password.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-05-02T06:50:51Z
- **Completed:** 2026-05-02T06:57:09Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

### Task 1: Add emailVerified to AuthSession and localStorage in useAuth.ts

- Added `emailVerified: boolean` field to `AuthSession` interface.
- Added `emailVerified: true` to `LOCAL_SESSION` constant (local proxy mode = always verified).
- Added `burnlens_email_verified` localStorage read during hydration: `emailVerifiedRaw === null ? true : emailVerifiedRaw === "true"` (null → true grandfathered users).
- Passed `emailVerified` into the `setSession({...})` call for remote sessions.
- Added `localStorage.removeItem("burnlens_email_verified")` in `logout()` cleanup block.

### Task 2: Store emailVerified in localStorage after login/signup + Forgot password flow in setup/page.tsx

- Extended `storeSession()` type signature to accept optional `email_verified?: boolean` field.
- Added `localStorage.setItem("burnlens_email_verified", String(data.email_verified ?? true))` inside `storeSession()` so both login and signup paths persist the value.
- Added four state variables: `showForgotPw`, `forgotEmail`, `forgotMsg`, `forgotLoading`.
- Added `handleForgotSubmit()` async function: POSTs to `BASE_URL/auth/reset-password`, sets neutral success message (anti-enumeration: always 200), catches network errors.
- Added inline Forgot password? toggle after the Sign in button: shows trigger link when `!showForgotPw`, reveals email form when `showForgotPw` is true.
- Inline form has: email input, "Send reset link" CTA (loading state "Sending…"), success/error message display, "← Back to sign in" reset button.

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add emailVerified to AuthSession and localStorage in useAuth.ts | 5bebdab | frontend/src/lib/hooks/useAuth.ts |
| 2 | Store emailVerified in localStorage + Forgot password flow in setup/page.tsx | 679085d | frontend/src/app/setup/page.tsx |

## Files Created/Modified

- `frontend/src/lib/hooks/useAuth.ts` — 7 lines added: AuthSession.emailVerified field, LOCAL_SESSION emailVerified:true, emailVerifiedRaw/emailVerified hydration variables, emailVerified in setSession call, removeItem in logout
- `frontend/src/app/setup/page.tsx` — 61 lines added: storeSession email_verified param + setItem, 4 state vars, handleForgotSubmit handler, Forgot password? JSX block

## Decisions Made

- `storeSession()` extended with optional `email_verified` param rather than duplicating `setItem` calls in each handler — keeps session persistence in one function.
- `data.email_verified ?? true` fallback: legacy backend responses without the field treated as verified to avoid spuriously showing the verification banner to existing users.
- `handleForgotSubmit` always sets the neutral success message even on network failure — except a genuine catch that sets "Something went wrong." to give user some feedback.

## Deviations from Plan

None — plan executed exactly as written. The `storeSession()` extension approach was the natural interpretation of "locate the burnlens_plan setItem block and add after it" since that block lives inside `storeSession()`.

## Known Stubs

None — both changes are fully wired:
- `emailVerified` flows from localStorage → `AuthSession` → downstream consumers (Plan 05b BillingStatusBanner)
- `handleForgotSubmit` calls the real `POST /auth/reset-password` endpoint built in Plan 03b

## Threat Flags

None — consistent with plan threat model. `burnlens_email_verified` in localStorage can only hide/show the UI verification banner; server-side `email_verified_at` column is the authoritative gate. No privilege escalation possible.

## Self-Check: PASSED

- `frontend/src/lib/hooks/useAuth.ts`: FOUND (modified)
- `frontend/src/app/setup/page.tsx`: FOUND (modified)
- Commit 5bebdab exists: FOUND
- Commit 679085d exists: FOUND
- `emailVerified: boolean` in AuthSession interface: FOUND (line 17)
- `emailVerified: true` in LOCAL_SESSION: FOUND (line 39)
- `burnlens_email_verified` read in hydration: FOUND (line 60)
- `emailVerifiedRaw === null ? true : emailVerifiedRaw === "true"`: FOUND (line 62)
- `emailVerified` in setSession call: FOUND (line 82)
- `localStorage.removeItem("burnlens_email_verified")` in logout: FOUND (line 100)
- `localStorage.setItem("burnlens_email_verified"` in storeSession: FOUND
- `data.email_verified`: FOUND
- `showForgotPw` state: FOUND
- `handleForgotSubmit`: FOUND
- `Forgot password?`: FOUND in JSX
- `auth/reset-password` in fetch call: FOUND

---
*Phase: 11-auth-essentials*
*Completed: 2026-05-02*
