---
phase: 11-auth-essentials
plan: 05b
type: execute
wave: 3
depends_on: ["05a"]
files_modified:
  - frontend/src/app/reset-password/page.tsx
  - frontend/src/app/verify-email/page.tsx
  - frontend/src/components/BillingStatusBanner.tsx
autonomous: true
requirements: [AUTH-01, AUTH-02, AUTH-07]
must_haves:
  truths:
    - "/reset-password page renders a new-password form; on submit POSTs to POST /auth/reset-password/confirm with token (from URL ?token=) and new_password"
    - "/verify-email page calls GET /auth/verify-email?token= on mount; shows success or error state"
    - "/verify-email sets localStorage burnlens_email_verified=true on success so the banner dismisses without re-login"
    - "Both pages wrap useSearchParams in <Suspense> (required by Next.js App Router)"
    - "BillingStatusBanner renders email verification amber banner when session.emailVerified === false and !isLocal"
    - "Email verification banner matches existing BillingStatusBanner height=40 and border-left=3px style"
    - "Existing past_due banner behavior completely preserved"
  artifacts:
    - path: "frontend/src/app/reset-password/page.tsx"
      provides: "Password reset form page — validates token on submit, sets new password"
      exports: []
    - path: "frontend/src/app/verify-email/page.tsx"
      provides: "Email verification confirmation page — calls backend on mount"
      exports: []
    - path: "frontend/src/components/BillingStatusBanner.tsx"
      provides: "Email verification banner below billing banner for unverified users"
      exports: ["BillingStatusBanner"]
  key_links:
    - from: "frontend/src/app/reset-password/page.tsx"
      to: "burnlens_cloud/auth.py POST /auth/reset-password/confirm (Plan 03b)"
      via: "POST ${API_BASE}/auth/reset-password/confirm"
      pattern: "reset-password/confirm"
    - from: "frontend/src/app/verify-email/page.tsx"
      to: "burnlens_cloud/auth.py GET /auth/verify-email (Plan 03b)"
      via: "GET ${API_BASE}/auth/verify-email?token="
      pattern: "verify-email"
    - from: "frontend/src/components/BillingStatusBanner.tsx"
      to: "frontend/src/lib/hooks/useAuth.ts AuthSession.emailVerified (Plan 05a)"
      via: "session?.emailVerified === false"
      pattern: "emailVerified"
---

<objective>
Create two new Next.js pages (`/reset-password` and `/verify-email`) and extend `BillingStatusBanner.tsx` with an amber email-verification prompt. All three reuse the `.sp-*` CSS shell from `setup/page.tsx`.

This is Part B of the split from original Plan 05. Depends on Plan 05a for `AuthSession.emailVerified`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/11-auth-essentials/11-CONTEXT.md
@.planning/phases/11-auth-essentials/11-UI-SPEC.md
@frontend/src/app/setup/page.tsx
@frontend/src/components/BillingStatusBanner.tsx
@frontend/src/lib/hooks/useAuth.ts

<interfaces>
<!-- BillingStatusBanner.tsx current rendering:
export function BillingStatusBanner({ billing, session }: Props) {
  if (billing?.status !== "past_due") return null;
  return <div role="status" style={{ height: 40, ... }}>...</div>;
}
-->

<!-- setup/page.tsx CSS: copy the full <style> block verbatim into new pages -->

<!-- AuthSession.emailVerified: boolean  (added by Plan 05a) -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create /reset-password/page.tsx</name>
  <files>frontend/src/app/reset-password/page.tsx</files>
  <read_first>
    - frontend/src/app/setup/page.tsx lines 1-60 (imports, component structure, .sp-* CSS classes)
    - frontend/src/app/setup/page.tsx (full style block — copy verbatim into new file)
    - .planning/phases/11-auth-essentials/11-UI-SPEC.md §Routes section (reset-password page spec)
  </read_first>
  <action>
Create `frontend/src/app/reset-password/page.tsx`. It is a `"use client"` component that:

1. Reads `?token=` from `useSearchParams()`.
2. Shows a form with a "New password" input (type="password", minLength=8, maxLength=128).
3. On submit, POSTs `{ token, new_password }` to `${API_BASE}/auth/reset-password/confirm`.
4. On success: shows a confirmation message and calls `router.push("/setup")` after 2 seconds.
5. On error: shows the API error message as text (not injected as HTML).
6. If no token in URL: shows "This link is invalid or has expired."
7. Wraps the inner component in `<Suspense>` (required by Next.js App Router for `useSearchParams`).

```tsx
"use client";

import { useState, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8420";

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token");

  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  if (!token) {
    return (
      <div className="sp-card">
        <h1 className="sp-title">Reset password</h1>
        <p className="sp-desc">This link is invalid or has expired. Request a new one from the sign-in page.</p>
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/reset-password/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = typeof body.detail === "string" ? body.detail : "Reset failed. The link may have expired.";
        throw new Error(detail);
      }
      setSuccess(true);
      setTimeout(() => router.push("/setup"), 2000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  if (success) {
    return (
      <div className="sp-card">
        <h1 className="sp-title">Password updated</h1>
        <p className="sp-desc">Redirecting to sign in…</p>
      </div>
    );
  }

  return (
    <div className="sp-card">
      <h1 className="sp-title">Set a new password</h1>
      <p className="sp-desc">Choose a password with at least 8 characters.</p>
      <form onSubmit={handleSubmit} className="sp-form">
        <div className="sp-field">
          <label className="sp-label">New password</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            minLength={8}
            maxLength={128}
            required
            className="sp-input"
            placeholder="••••••••"
          />
        </div>
        {error && <p className="sp-error">{error}</p>}
        <button type="submit" className="sp-btn-primary" disabled={loading}>
          {loading ? "Updating…" : "Set new password"}
        </button>
      </form>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="sp-root">
      <div className="sp-left">
        <div className="sp-brand">
          <span className="sp-logo">BurnLens</span>
          <p className="sp-tagline">See where your AI budget goes.</p>
        </div>
      </div>
      <div className="sp-right">
        <Suspense fallback={<div className="sp-card"><p>Loading…</p></div>}>
          <ResetPasswordForm />
        </Suspense>
      </div>
    </div>
  );
}
```

After writing the component, append the `<style>` block copied verbatim from `setup/page.tsx`.
  </action>
  <acceptance_criteria>
    - File `frontend/src/app/reset-password/page.tsx` exists
    - Contains `"use client"`
    - Contains `useSearchParams` import from `"next/navigation"`
    - Contains `searchParams.get("token")`
    - Contains POST to `auth/reset-password/confirm`
    - Contains `router.push("/setup")` on success
    - Contains `Suspense` wrapper
    - Error messages rendered as text content (no raw HTML injection)
    - `cd frontend && npx tsc --noEmit 2>&1 | grep -c "reset-password"` → `0`
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Create /verify-email/page.tsx</name>
  <files>frontend/src/app/verify-email/page.tsx</files>
  <read_first>
    - frontend/src/app/reset-password/page.tsx (just created — use same shell pattern)
    - .planning/phases/11-auth-essentials/11-UI-SPEC.md §Routes section (verify-email page spec)
  </read_first>
  <action>
Create `frontend/src/app/verify-email/page.tsx`. It calls `GET /auth/verify-email?token=` on mount (inside `useEffect`) and shows success or error. On success, sets `localStorage.setItem("burnlens_email_verified", "true")` so the banner dismisses without requiring a re-login.

```tsx
"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8420";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("This verification link is invalid.");
      return;
    }
    fetch(`${API_BASE}/auth/verify-email?token=${encodeURIComponent(token)}`)
      .then(async res => {
        if (res.ok) {
          localStorage.setItem("burnlens_email_verified", "true");
          setStatus("success");
          setMessage("Your email has been verified. You're all set!");
        } else {
          const body = await res.json().catch(() => ({}));
          const detail = typeof body.detail === "string" ? body.detail : "This link is invalid or has expired.";
          setStatus("error");
          setMessage(detail);
        }
      })
      .catch(() => {
        setStatus("error");
        setMessage("Could not connect. Please try again.");
      });
  }, [token]);

  return (
    <div className="sp-card">
      <h1 className="sp-title">Email verification</h1>
      {status === "loading" && <p className="sp-desc">Verifying…</p>}
      {status === "success" && (
        <>
          <p className="sp-desc">{message}</p>
          <Link href="/dashboard" className="sp-btn-primary" style={{ display: "inline-block", marginTop: 16, textDecoration: "none" }}>
            Go to dashboard
          </Link>
        </>
      )}
      {status === "error" && (
        <>
          <p className="sp-desc">{message}</p>
          <Link href="/setup" className="sp-btn-primary" style={{ display: "inline-block", marginTop: 16, textDecoration: "none" }}>
            Back to sign in
          </Link>
        </>
      )}
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <div className="sp-root">
      <div className="sp-left">
        <div className="sp-brand">
          <span className="sp-logo">BurnLens</span>
          <p className="sp-tagline">See where your AI budget goes.</p>
        </div>
      </div>
      <div className="sp-right">
        <Suspense fallback={<div className="sp-card"><p>Verifying…</p></div>}>
          <VerifyEmailContent />
        </Suspense>
      </div>
    </div>
  );
}
```

After writing the component, append the `<style>` block copied verbatim from `setup/page.tsx`.
  </action>
  <acceptance_criteria>
    - File `frontend/src/app/verify-email/page.tsx` exists
    - Contains `"use client"`
    - Contains `useEffect` that fetches `auth/verify-email?token=`
    - Contains `localStorage.setItem("burnlens_email_verified", "true")` on success
    - Contains `Suspense` wrapper
    - Error/success messages rendered as text (no raw HTML injection)
    - `cd frontend && npx tsc --noEmit 2>&1 | grep -c "verify-email"` → `0`
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 3: Add email verification banner to BillingStatusBanner.tsx</name>
  <files>frontend/src/components/BillingStatusBanner.tsx</files>
  <read_first>
    - frontend/src/components/BillingStatusBanner.tsx (entire file — current props interface, banner render, existing height=40 and border-left=3px values)
    - frontend/src/lib/hooks/useAuth.ts (confirm AuthSession export name and emailVerified field from Plan 05a)
    - .planning/phases/11-auth-essentials/11-UI-SPEC.md (email verification banner visual spec)
  </read_first>
  <action>
Extend `BillingStatusBanner.tsx` to render an email verification amber banner:

1. Import `AuthSession` from `@/lib/hooks/useAuth`.
2. Extend `Props` to accept `session?: AuthSession | null`.
3. Add `showVerify` derived from `session?.emailVerified === false && session?.isLocal === false`.
4. Render both banners: past_due first (existing content unchanged), verify_email below.

The new Props interface:
```typescript
import type { AuthSession } from "@/lib/hooks/useAuth";

interface Props {
  billing?: { status: string } | null;
  session?: AuthSession | null;
}
```

The new return:
```typescript
export function BillingStatusBanner({ billing, session }: Props) {
  const showPastDue = billing?.status === "past_due";
  const showVerify = session?.emailVerified === false && session?.isLocal === false;

  if (!showPastDue && !showVerify) return null;

  return (
    <>
      {showPastDue && (
        /* PRESERVE existing past_due banner JSX exactly — copy it verbatim from the file */
      )}
      {showVerify && (
        <div
          role="status"
          aria-label="Email verification required"
          style={{
            height: 40,
            background: "var(--color-warning-bg, #fffbeb)",
            borderLeft: "3px solid var(--color-warning, #d97706)",
            display: "flex",
            alignItems: "center",
            padding: "0 24px",
            fontSize: "var(--fs-13)",
            color: "var(--color-warning-text, #92400e)",
            gap: 8,
          }}
        >
          <span>Please verify your email address.</span>
          <a
            href="/setup"
            style={{ color: "inherit", fontWeight: 500, textDecoration: "underline", marginLeft: 4 }}
          >
            Resend verification email
          </a>
        </div>
      )}
    </>
  );
}
```

**Critical:** Read the file first to copy the existing past_due banner JSX verbatim. Do NOT change its content.

Call sites of BillingStatusBanner that do not pass `session` are safe — the prop defaults to `undefined` so `showVerify` evaluates to `false`.
  </action>
  <acceptance_criteria>
    - frontend/src/components/BillingStatusBanner.tsx imports `AuthSession` from `@/lib/hooks/useAuth`
    - frontend/src/components/BillingStatusBanner.tsx contains `showVerify`
    - frontend/src/components/BillingStatusBanner.tsx contains `emailVerified === false`
    - frontend/src/components/BillingStatusBanner.tsx contains `aria-label="Email verification required"`
    - frontend/src/components/BillingStatusBanner.tsx still contains `status === "past_due"` (existing behavior preserved)
    - `cd frontend && npx tsc --noEmit 2>&1 | grep -c "BillingStatusBanner"` → `0`
  </acceptance_criteria>
</task>

</tasks>

<verification>
1. `ls frontend/src/app/reset-password/page.tsx frontend/src/app/verify-email/page.tsx` → both exist (exit 0)
2. `grep "burnlens_email_verified" frontend/src/app/verify-email/page.tsx` → match found
3. `grep "showVerify\|emailVerified" frontend/src/components/BillingStatusBanner.tsx` → match found
4. `grep "past_due" frontend/src/components/BillingStatusBanner.tsx` → still present (existing behavior)
5. `cd frontend && npx tsc --noEmit` → exits 0 (no TypeScript errors)
</verification>

<threat_model>
## Security Threat Model (ASVS L1)

| Threat | Severity | Mitigation |
|--------|----------|-----------|
| Reset token exposed in browser history via URL query param | MEDIUM | Token is single-use (claimed on submit — Plan 03b atomic UPDATE) so replaying from history returns 400; 1h expiry limits window |
| XSS via error message text | MEDIUM | Error messages from `err.message` or hardcoded strings; rendered as React text nodes, never injected as raw HTML markup |
| Clickjacking on auth pages | LOW | Existing infrastructure-level X-Frame-Options headers apply to all Next.js pages |
| localStorage emailVerified tampered | LOW | Writing `emailVerified=true` only hides the UI reminder banner — no privilege escalation; server-side email_verified_at is authoritative |
| verify-email page polled to probe token validity | LOW | Token claimed atomically on first successful request; subsequent requests return 400 |

No high-severity unmitigated threats from frontend-only changes.
</threat_model>

<must_haves>
- /reset-password page wraps useSearchParams in Suspense (Next.js App Router requirement)
- /verify-email page calls backend on mount and sets localStorage.burnlens_email_verified=true on success
- BillingStatusBanner shows verify banner only for cloud sessions with emailVerified=false
- Existing past_due banner behavior completely preserved
- TypeScript compiles without errors for all 3 files
</must_haves>
