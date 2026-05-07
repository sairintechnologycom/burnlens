---
phase: 11-auth-essentials
plan: "05b"
subsystem: frontend
tags: [auth, password-reset, email-verification, BillingStatusBanner, sp-shell]

# Dependency graph
requires:
  - 11-05a (AuthSession.emailVerified from useAuth.ts)
  - 11-03b (backend /auth/reset-password/confirm and /auth/verify-email endpoints)
provides:
  - frontend/src/app/reset-password/page.tsx
  - frontend/src/app/verify-email/page.tsx
  - frontend/src/components/BillingStatusBanner.tsx::showVerify email verification banner
affects:
  - frontend/src/components/Shell.tsx (passes session to BillingStatusBanner)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Suspense wrapper around useSearchParams — required by Next.js App Router for all useSearchParams consumers"
    - "sp-* CSS shell verbatim copy — new auth pages reuse setup/page.tsx style block without shared CSS file"
    - "Default + named export dual pattern — BillingStatusBanner named export for prop-based use; default connected wrapper reads billing from context"
    - "localStorage.setItem on verify success — hides banner without re-login; server-side email_verified_at remains authoritative"

key-files:
  created:
    - frontend/src/app/reset-password/page.tsx
    - frontend/src/app/verify-email/page.tsx
  modified:
    - frontend/src/components/BillingStatusBanner.tsx
    - frontend/src/components/Shell.tsx

key-decisions:
  - "BillingStatusBanner retains default export (connected wrapper reads from useBilling context) plus adds named export with explicit Props — Shell.tsx updated to pass session, no downstream breakage"
  - "verify-email page uses lucide-react CheckCircle2/XCircle icons per UI-SPEC states spec — plan snippet was minimalist but UI-SPEC explicitly specified icons"
  - "reset-password page uses existing sp-form-area/sp-form-title/sp-form-sub/sp-field classes from setup/page.tsx rather than plan sp-card/sp-title/sp-desc aliases (those classes do not exist in the style block)"

requirements-completed: [AUTH-01, AUTH-02, AUTH-07]

# Metrics
duration: "21min"
completed: "2026-05-02"
---

# Phase 11 Plan 05b: /reset-password, /verify-email pages + BillingStatusBanner email verification Summary

**Two new Next.js auth pages (/reset-password and /verify-email) using the sp-* shell, plus an email verification amber banner in BillingStatusBanner driven by session.emailVerified.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-05-02T07:01:23Z
- **Completed:** 2026-05-02T07:22:49Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

### Task 1: Create /reset-password/page.tsx

- Created `frontend/src/app/reset-password/page.tsx` with `"use client"` directive.
- Reads `?token=` from `useSearchParams()`.
- Invalid-token state: shows message and back-to-sign-in link.
- Form with password input (minLength=8, maxLength=128, required).
- On submit: POSTs `{ token, new_password }` to `${API_BASE}/auth/reset-password/confirm`.
- On success: shows "Password updated" confirmation and calls `router.push("/setup")` after 2s.
- On error: shows API error as text (rendered as React text node, not injected markup).
- Inner `ResetPasswordForm` wrapped in `<Suspense>` as required by Next.js App Router.
- Full sp-* CSS shell copied from setup/page.tsx.

### Task 2: Create /verify-email/page.tsx

- Created `frontend/src/app/verify-email/page.tsx` with `"use client"` directive.
- `useEffect` on mount: fetches `GET ${API_BASE}/auth/verify-email?token=${encodeURIComponent(token)}`.
- On success: `localStorage.setItem("burnlens_email_verified", "true")`, shows CheckCircle2 icon + "Email verified" heading + CTA to dashboard.
- On error: shows XCircle icon + error message as React text node + CTA to dashboard.
- Loading state: "Verifying your email..." body with `aria-live="polite"`.
- Inner `VerifyEmailContent` wrapped in `<Suspense>`.
- Full sp-* CSS shell copied from setup/page.tsx.

### Task 3: Add email verification banner to BillingStatusBanner.tsx + update Shell.tsx

- Imported `AuthSession` type from `@/lib/hooks/useAuth`.
- Added `Props` interface with `billing?: { status: string } | null` and `session?: AuthSession | null`.
- `showVerify` derived from `session?.emailVerified === false && session?.isLocal === false`.
- Named export `BillingStatusBanner` renders both banners: past_due first (existing content preserved verbatim), verify_email below.
- Email verification banner: height 40, amber border-left 3px, Mail icon (14px), `aria-label="Email verification required"`, `aria-live="polite"`.
- Kept default export as a connected wrapper that reads billing from `useBilling()` context and accepts optional `session` prop.
- Updated `Shell.tsx` to pass `session` to `<BillingStatusBanner session={session} />`.

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create /reset-password page | 8c7c10e | frontend/src/app/reset-password/page.tsx |
| 2 | Create /verify-email page | 1b2dc1b | frontend/src/app/verify-email/page.tsx |
| 3 | Email verification banner in BillingStatusBanner + Shell.tsx session | 6e3f9bd | frontend/src/components/BillingStatusBanner.tsx, frontend/src/components/Shell.tsx |

## Files Created/Modified

- `frontend/src/app/reset-password/page.tsx` — 316 lines: full page with token check, form, success/error states, Suspense wrapper, sp-* CSS shell
- `frontend/src/app/verify-email/page.tsx` — 283 lines: full page with useEffect GET, localStorage.setItem on success, CheckCircle2/XCircle icons, Suspense wrapper, sp-* CSS shell
- `frontend/src/components/BillingStatusBanner.tsx` — 97 lines added: AuthSession import, Props interface, showVerify logic, email verification banner JSX, named export + default connected wrapper
- `frontend/src/components/Shell.tsx` — 1 line changed: `<BillingStatusBanner />` to `<BillingStatusBanner session={session} />`

## Decisions Made

- **BillingStatusBanner dual export:** The existing file used a default export with no props. Rather than a breaking rename, we kept the default export as a connected wrapper and added the named `BillingStatusBanner` as the testable pure component. Shell.tsx updated to pass `session` so the email verification banner activates.
- **sp-* class names:** The plan code snippet used `sp-card`, `sp-title`, `sp-desc` but the actual setup/page.tsx style block defines `sp-form-area`, `sp-form-title`, `sp-form-sub`. Used the real class names so the copied style block works without modification.
- **lucide-react icons:** Plan's verify-email snippet was minimalist (no icons) but the UI-SPEC explicitly specified `CheckCircle2` (success) and `XCircle` (error) icons at 24px. Added them per UI-SPEC — lucide-react is already installed and used in BillingStatusBanner.

## Deviations from Plan

### Auto-corrected Issues

**1. [Rule 1 - Bug] sp-* class names corrected**
- **Found during:** Task 1 implementation
- **Issue:** Plan code snippet used `sp-card`, `sp-title`, `sp-desc` CSS classes not defined in the setup/page.tsx style block (which has `sp-form-area`, `sp-form-title`, `sp-form-sub`)
- **Fix:** Used the actual class names from setup/page.tsx style block throughout both pages
- **Files modified:** frontend/src/app/reset-password/page.tsx, frontend/src/app/verify-email/page.tsx

**2. [Rule 2 - Missing functionality] lucide-react icons added to verify-email**
- **Found during:** Task 2 implementation
- **Issue:** Plan snippet omitted icons but UI-SPEC section States explicitly specifies CheckCircle2 (success) and XCircle (error) at 24px
- **Fix:** Added CheckCircle2 and XCircle from lucide-react (already installed)
- **Files modified:** frontend/src/app/verify-email/page.tsx

## Known Stubs

None — all three files are fully wired:
- `/reset-password` calls real `POST /auth/reset-password/confirm` endpoint (Plan 03b)
- `/verify-email` calls real `GET /auth/verify-email` endpoint (Plan 03b); sets localStorage on success
- `BillingStatusBanner.showVerify` reads `session.emailVerified` from `useAuth` (Plan 05a); Shell.tsx passes the live session object

## Threat Flags

None — consistent with plan threat model. All mitigations confirmed:
- Error messages rendered as React text nodes (no raw HTML injection)
- Token only in URL query param (single-use backend claim already in Plan 03b)
- `burnlens_email_verified` localStorage write only controls UI banner visibility; server-side `email_verified_at` is authoritative

## Self-Check: PASSED

- `frontend/src/app/reset-password/page.tsx`: FOUND
- `frontend/src/app/verify-email/page.tsx`: FOUND
- `frontend/src/components/BillingStatusBanner.tsx`: FOUND (modified)
- `frontend/src/components/Shell.tsx`: FOUND (modified)
- Commit 8c7c10e exists: FOUND
- Commit 1b2dc1b exists: FOUND
- Commit 6e3f9bd exists: FOUND
- `"use client"` in reset-password: FOUND
- `useSearchParams` in reset-password: FOUND
- `searchParams.get("token")` in reset-password: FOUND
- `reset-password/confirm` in reset-password: FOUND
- `router.push("/setup")` in reset-password: FOUND
- `Suspense` in reset-password: FOUND
- `"use client"` in verify-email: FOUND
- `useEffect` in verify-email: FOUND
- `auth/verify-email` in verify-email: FOUND
- `localStorage.setItem("burnlens_email_verified", "true")` in verify-email: FOUND
- `Suspense` in verify-email: FOUND
- `AuthSession` import in BillingStatusBanner: FOUND
- `showVerify` in BillingStatusBanner: FOUND
- `emailVerified === false` in BillingStatusBanner: FOUND
- `aria-label="Email verification required"` in BillingStatusBanner: FOUND
- `status === "past_due"` in BillingStatusBanner: FOUND
- TypeScript errors in our files: 0

---
*Phase: 11-auth-essentials*
*Completed: 2026-05-02*
