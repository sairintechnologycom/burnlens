---
phase: 16-api-key-management
plan: 06
status: complete
date: 2026-05-12
requirements: [AUTH-08]
files_modified:
  - frontend/src/components/BillingStatusBanner.tsx
---

# 16-06 — BillingStatusBanner Client-Side AUTH-08 Closure

## Outcome

Single surgical edit: the resend-verification fetch no longer sends a body
or Content-Type header. It now relies entirely on the HttpOnly session
cookie (`credentials: "include"`) to identify the caller. Pairs with the
16-02 backend rewrite that derives identity from the JWT, closing AUTH-08
for API-key signup users whose `ownerEmail` is `null` in localStorage.

## Diff (verbatim)

```diff
       await fetch(`${API_BASE}/auth/resend-verification`, {
         method: "POST",
-        headers: { "Content-Type": "application/json" },
-        body: JSON.stringify({ email: session?.ownerEmail ?? "" }),
         credentials: "include",
       });
```

## Verification

- `grep -nE '(headers:|body:|ownerEmail)' frontend/src/components/BillingStatusBanner.tsx`
  → no matches (handler is body-less, no ownerEmail reads).
- `credentials: "include"` retained at line 38.
- `tsc --noEmit` clean (exit 0). No orphaned types or unused imports.
- Visual UX preserved: button copy ("Resend verification email"), in-flight
  state, success/error toasts unchanged from Phase 11.

## Notes

- `session` prop is still consumed at line 29 for `emailVerified` / `isLocal`,
  so it remains in scope. Only the `session?.ownerEmail` read was removed.
- `useAuth.ts` and `setup/page.tsx` continue to track `owner_email` locally
  for display purposes — out of scope for AUTH-08 closure (D-13).

## Self-Check: PASSED
