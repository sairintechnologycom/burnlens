---
status: partial
phase: 10-feature-gating-usage-visibility-ui
source: [10-VERIFICATION.md]
started: 2026-04-28T04:25:00Z
updated: 2026-04-28T04:25:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Free-tier user lands on /teams
expected: Frosted-glass TeamsSkeleton visible behind LockedPanel overlay; title "Team breakdowns requires Teams plan"; CTA "Upgrade to Teams" opens Paddle checkout overlay (no router hop).
result: [pending]

### 2. Cloud-tier user clicks Create key in API Keys card after creating one key
expected: Create-key button is disabled pre-emptively (no 402 round-trip); cap-banner shows "Your Cloud plan allows 1 API keys. Upgrade to Teams for more."; Upgrade button opens Paddle checkout for Teams plan, NOT Cloud.
result: [pending]

### 3. Usage meter color transitions across thresholds
expected: At 79% bar shows cyan/green; at 80% transitions to amber; at 100% transitions to red with overflow percentage label "(120%)" shown; bar width clamps to 100%.
result: [pending]

### 4. Click sidebar usage meter from any dashboard page
expected: Browser navigates to /settings#usage and scrolls/anchors to Usage card; daily bar chart loads with cumulative-color bars from /billing/usage/daily.
result: [pending]

### 5. Create then revoke an API key
expected: Create key shows plaintext modal exactly once; backdrop click and Esc do NOT dismiss; only "I've saved it" button dismisses; after dismiss plaintext is cleared from React state. Revoke requires typing exact key name (case-sensitive).
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
