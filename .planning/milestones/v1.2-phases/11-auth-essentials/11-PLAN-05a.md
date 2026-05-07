---
phase: 11-auth-essentials
plan: 05a
type: execute
wave: 3
depends_on: ["03b"]
files_modified:
  - frontend/src/lib/hooks/useAuth.ts
  - frontend/src/app/setup/page.tsx
autonomous: true
requirements: [AUTH-01, AUTH-06]
must_haves:
  truths:
    - "AuthSession interface gains emailVerified: boolean field"
    - "LOCAL_SESSION has emailVerified: true"
    - "useAuth hydration reads burnlens_email_verified from localStorage; null → true (grandfathered)"
    - "useAuth logout removes burnlens_email_verified from localStorage"
    - "setup/page.tsx stores emailVerified from login/signup response: localStorage.setItem('burnlens_email_verified', String(data.email_verified ?? true))"
    - "setup/page.tsx has a 'Forgot password?' trigger that reveals an inline email form calling POST /auth/reset-password"
  artifacts:
    - path: "frontend/src/lib/hooks/useAuth.ts"
      provides: "emailVerified field on AuthSession + localStorage persistence"
      exports: ["AuthSession", "useAuth"]
    - path: "frontend/src/app/setup/page.tsx"
      provides: "'Forgot password?' flow inline on setup page + stores emailVerified in localStorage"
      exports: []
  key_links:
    - from: "frontend/src/lib/hooks/useAuth.ts::AuthSession.emailVerified"
      to: "Plan 05b BillingStatusBanner"
      via: "session?.emailVerified === false"
      pattern: "emailVerified"
---

<objective>
Add `emailVerified: boolean` to `AuthSession` in `useAuth.ts`, wire it to `localStorage`, and update `setup/page.tsx` to store `emailVerified` after login/signup and show a "Forgot password?" inline form.

This is Part A of the split from original Plan 05. Part B (`11-PLAN-05b.md`) adds the two new pages and the BillingStatusBanner extension.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/11-auth-essentials/11-CONTEXT.md
@frontend/src/lib/hooks/useAuth.ts
@frontend/src/app/setup/page.tsx

<interfaces>
<!-- AuthSession (useAuth.ts):
export interface AuthSession {
  token: string;
  workspaceId: string;
  workspaceName: string;
  plan: string;
  apiKey: string;
  isLocal: boolean;
}
Add: emailVerified: boolean;
-->

<!-- localStorage keys (non-sensitive workspace metadata):
burnlens_workspace_id, burnlens_workspace_name, burnlens_plan, burnlens_api_key
New key: burnlens_email_verified ("true"/"false" string)
-->

<!-- setup/page.tsx key patterns:
- API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8420"
- localStorage.setItem("burnlens_plan", data.workspace.plan) after login/signup
- CSS class prefix: .sp-* (scoped to this page)
-->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add emailVerified to AuthSession and localStorage in useAuth.ts</name>
  <files>frontend/src/lib/hooks/useAuth.ts</files>
  <read_first>
    - frontend/src/lib/hooks/useAuth.ts (entire file — confirm current AuthSession fields and localStorage read pattern)
  </read_first>
  <action>
Four changes to `useAuth.ts`:

1. **AuthSession interface** — add `emailVerified: boolean` field:
```typescript
export interface AuthSession {
  token: string;
  workspaceId: string;
  workspaceName: string;
  plan: string;
  apiKey: string;
  isLocal: boolean;
  emailVerified: boolean;
}
```

2. **LOCAL_SESSION constant** — add `emailVerified: true` (local mode = always verified):
```typescript
const LOCAL_SESSION: AuthSession = {
  token: "local",
  workspaceId: "local",
  workspaceName: "Local",
  plan: "free",
  apiKey: "local",
  isLocal: true,
  emailVerified: true,
};
```

3. **Session hydration from localStorage** — read `burnlens_email_verified` alongside existing keys:
```typescript
    const emailVerifiedRaw = localStorage.getItem("burnlens_email_verified");
    // Treat missing (null) as true — grandfathered users have no stored value.
    const emailVerified = emailVerifiedRaw === null ? true : emailVerifiedRaw === "true";
```
Then pass `emailVerified` to `setSession({..., emailVerified})`.

4. **logout()** — add cleanup for `burnlens_email_verified` in the existing removeItem block:
```typescript
    localStorage.removeItem("burnlens_email_verified");
```
  </action>
  <acceptance_criteria>
    - frontend/src/lib/hooks/useAuth.ts contains `emailVerified: boolean` in AuthSession interface
    - frontend/src/lib/hooks/useAuth.ts contains `emailVerified: true` in LOCAL_SESSION
    - frontend/src/lib/hooks/useAuth.ts contains `burnlens_email_verified`
    - frontend/src/lib/hooks/useAuth.ts contains `emailVerifiedRaw === null ? true : emailVerifiedRaw === "true"`
    - frontend/src/lib/hooks/useAuth.ts logout removes `burnlens_email_verified`
    - `cd frontend && npx tsc --noEmit 2>&1 | grep -c "useAuth"` → `0`
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Store emailVerified in localStorage after login/signup in setup/page.tsx</name>
  <files>frontend/src/app/setup/page.tsx</files>
  <read_first>
    - frontend/src/app/setup/page.tsx (search for `localStorage.setItem("burnlens_plan"` — the exact block where other session metadata is stored after login/signup success)
    - frontend/src/app/setup/page.tsx (full file — to understand the form structure for placing the Forgot password trigger)
  </read_first>
  <action>
**Change 1: Store emailVerified after login/signup.**

Locate every block where `localStorage.setItem("burnlens_plan", data.workspace.plan)` is called. After each such line add:

```typescript
localStorage.setItem("burnlens_email_verified", String(data.email_verified ?? true));
```

The `?? true` fallback handles legacy responses that don't include the field.

**Change 2: Forgot password flow.**

Add these state variables at the top of the component (alongside other useState declarations):
```typescript
const [showForgotPw, setShowForgotPw] = useState(false);
const [forgotEmail, setForgotEmail] = useState("");
const [forgotMsg, setForgotMsg] = useState<string | null>(null);
const [forgotLoading, setForgotLoading] = useState(false);
```

Add the submit handler (alongside other handler functions):
```typescript
async function handleForgotSubmit(e: React.FormEvent) {
  e.preventDefault();
  setForgotLoading(true);
  try {
    await fetch(`${API_BASE}/auth/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: forgotEmail }),
    });
    setForgotMsg("If an account exists, a reset link has been sent.");
  } catch {
    setForgotMsg("Something went wrong. Please try again.");
  } finally {
    setForgotLoading(false);
  }
}
```

Add the JSX below the sign-in form (find the closing tag of the login form and add after it):
```tsx
{!showForgotPw ? (
  <button
    type="button"
    onClick={() => setShowForgotPw(true)}
    style={{ background: "none", border: "none", color: "var(--color-accent)", cursor: "pointer", fontSize: "var(--fs-13)", padding: 0, marginTop: 8 }}
  >
    Forgot password?
  </button>
) : (
  <form onSubmit={handleForgotSubmit} style={{ marginTop: 16 }}>
    <p style={{ fontSize: "var(--fs-13)", color: "var(--color-text-muted)", marginBottom: 8 }}>
      Enter your email and we'll send a reset link.
    </p>
    <input
      type="email"
      value={forgotEmail}
      onChange={e => setForgotEmail(e.target.value)}
      placeholder="you@example.com"
      required
      className="sp-input"
      style={{ marginBottom: 8 }}
    />
    <button type="submit" className="sp-btn-primary" disabled={forgotLoading}>
      {forgotLoading ? "Sending…" : "Send reset link"}
    </button>
    {forgotMsg && <p style={{ fontSize: "var(--fs-13)", marginTop: 8, color: "var(--color-text-muted)" }}>{forgotMsg}</p>}
    <button
      type="button"
      onClick={() => { setShowForgotPw(false); setForgotMsg(null); }}
      style={{ background: "none", border: "none", color: "var(--color-text-muted)", cursor: "pointer", fontSize: "var(--fs-12)", marginTop: 4 }}
    >
      ← Back to sign in
    </button>
  </form>
)}
```
  </action>
  <acceptance_criteria>
    - frontend/src/app/setup/page.tsx contains `localStorage.setItem("burnlens_email_verified"` in at least one location
    - frontend/src/app/setup/page.tsx contains `data.email_verified`
    - frontend/src/app/setup/page.tsx contains `Forgot password?`
    - frontend/src/app/setup/page.tsx contains `auth/reset-password` in a fetch call
    - frontend/src/app/setup/page.tsx contains `showForgotPw` state variable
    - `cd frontend && npx tsc --noEmit 2>&1 | grep -c "setup/page"` → `0`
  </acceptance_criteria>
</task>

</tasks>

<verification>
1. `grep "emailVerified" frontend/src/lib/hooks/useAuth.ts` → shows interface field, LOCAL_SESSION, hydration, logout
2. `grep "burnlens_email_verified" frontend/src/lib/hooks/useAuth.ts` → match found
3. `grep "burnlens_email_verified\|Forgot password" frontend/src/app/setup/page.tsx` → both found
4. `cd frontend && npx tsc --noEmit 2>&1 | grep -E "useAuth|setup/page"` → no output (zero errors)
</verification>

<threat_model>
## Security Threat Model (ASVS L1)

| Threat | Severity | Mitigation |
|--------|----------|-----------|
| localStorage emailVerified tampered by attacker | LOW | Writing `emailVerified=true` only hides the UI banner — no privilege escalation; server-side email_verified_at is authoritative |
| Grandfathered user sees verification banner | LOW | `null → true` fallback in hydration means old users without stored value are treated as verified |

No high-severity threats in this plan.
</threat_model>

<must_haves>
- AuthSession.emailVerified typed as boolean; null localStorage value → true (grandfathered)
- logout() removes burnlens_email_verified
- setup/page.tsx stores emailVerified from every login/signup response path
- "Forgot password?" flow calls POST /auth/reset-password (always 200 backend)
- TypeScript compiles without errors for both modified files
</must_haves>
