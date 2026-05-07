---
status: complete
phase: 11-auth-essentials
source:
  - 11-01-SUMMARY.md
  - 11-02-SUMMARY.md
  - 11-03a-SUMMARY.md
  - 11-03b-SUMMARY.md
  - 11-04-SUMMARY.md
  - 11-05a-SUMMARY.md
  - 11-05b-SUMMARY.md
started: 2026-05-02T08:00:00Z
updated: 2026-05-02T08:30:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running backend server (Railway or local). Start the backend from scratch. The server boots without errors, init_db() runs its idempotent migrations (auth_tokens table + email_verified_at column on users), and GET /health (or any authenticated endpoint like GET /billing/summary) returns a live 200 response. No migration errors in logs.
result: pass

### 2. Forgot Password Toggle on Sign-in Page
expected: Open /setup (the sign-in page). Below the Sign in button, a "Forgot password?" link is visible. Clicking it collapses the sign-in form and reveals an inline email input with a "Send reset link" button. Clicking "← Back to sign in" toggles back to the login form.
result: pass

### 3. Password Reset Email Request (Anti-Enumeration)
expected: On the Forgot password? form, submit any email address (even one that doesn't exist). The form shows a neutral success message like "If that email is registered, a reset link is on its way." — no indication of whether the email was found. No error is shown.
result: pass

### 4. Reset Password Page Renders
expected: Navigate to /reset-password?token=sometoken. The page renders a "Reset your password" form with a password field. With an invalid token, submitting shows an error message like "Invalid or expired token" (rendered as text, not HTML). The page does NOT crash or show a Next.js error boundary.
result: pass

### 5. Email Verification Page Auto-Verifies
expected: Navigate to /verify-email?token=sometoken. The page shows "Verifying your email…" (loading state with aria-live). With an invalid token, it transitions to show an XCircle icon + error message + a CTA link back to the dashboard. With a valid token (from the verification email), it shows a CheckCircle2 icon + "Email verified" heading + CTA to dashboard, and localStorage burnlens_email_verified is set to "true".
result: pass

### 6. Email Verification Banner for New Users
expected: Register a new account (or log in as a user whose email is not verified). An amber banner appears at the top of the shell with a Mail icon and a "Verify your email" message. The banner includes a button to resend the verification email. The banner does NOT appear for users who are already verified or for local proxy mode users.
result: pass

### 7. Full Password Reset End-to-End
expected: (Requires live backend + real email delivery) Submit a registered email on the Forgot password? form. Receive an email with a reset link. Click the link — /reset-password?token=xxx loads. Enter a new password (8+ chars). Submit. See "Password updated" confirmation. After 2s, redirect to /setup. Log in with the new password successfully.
result: pass

### 8. Payment Receipt Email on Charge
expected: (Requires Paddle sandbox) Trigger a transaction.completed webhook event (e.g., complete a sandbox checkout or replay via Paddle dashboard). Confirm that the registered workspace owner receives a payment receipt email with the correct amount and billing period. Backend logs should show no errors for the transaction.completed handler.
result: pass

## Summary

total: 8
passed: 8
issues: 0
skipped: 0
pending: 0

## Gaps

[none yet]
