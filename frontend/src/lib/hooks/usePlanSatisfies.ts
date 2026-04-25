// Phase 10 D-08: plan-order helper used by Sidebar, LockedPanel, ApiKeysCard.
//
// IMPORTANT: This is a UI-affordance helper only. The backend `require_feature`
// middleware (Phase 9 GATE-05) is the authoritative entitlement gate. If this
// helper disagrees with the backend, the backend always wins — the locked
// teaser page (Plan 10-03) renders correctly when the API returns 402.

export const PLAN_ORDER = ["free", "cloud", "teams"] as const;
export type PlanName = (typeof PLAN_ORDER)[number];

/**
 * Returns true when `have` plan rank >= `need` plan rank.
 * - `need` undefined/null/empty → always satisfied (no gate).
 * - `have` null/undefined → never satisfied (treat as Free fallback).
 * - Either plan unknown to PLAN_ORDER → not satisfied (fail closed).
 */
export function planSatisfies(
  have: string | null | undefined,
  need?: string | null,
): boolean {
  if (!need) return true;
  if (!have) return false;
  const haveIdx = PLAN_ORDER.indexOf(have as PlanName);
  const needIdx = PLAN_ORDER.indexOf(need as PlanName);
  if (haveIdx < 0 || needIdx < 0) return false;
  return haveIdx >= needIdx;
}

// Phase 10 D-09: nav-affordance map. The backend middleware is still the
// authoritative gate; this map exists so the sidebar can pre-emptively render
// a lock glyph + plan subtitle for users whose plan does not satisfy the
// requirement. Drift risk is bounded — if this map is wrong, the locked
// teaser page still catches the 402 and renders correctly.
export const LOCKED_NAV: Record<string, string> = {
  "/teams": "teams",
  "/customers": "teams",
};

/**
 * Phase 10 D-26: derive the next paid plan up from the caller's current plan.
 * Used by ApiKeysCard cap-banner fallback when 402 doesn't carry
 * `required_plan`, and by any component that needs to suggest the next
 * upsell tier. Returns null when the caller is already on the top tier
 * (no further upsell — hide CTA).
 */
export function nextPlanFor(
  current: string | null | undefined,
): "cloud" | "teams" | null {
  if (!current || current === "free") return "cloud";
  if (current === "cloud") return "teams";
  // teams or unknown-future-tier → no upsell
  return null;
}
