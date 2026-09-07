// Plausible Analytics helpers. Loaded only when NEXT_PUBLIC_PLAUSIBLE_DOMAIN
// is configured (see PlausibleScript in app/layout.tsx). When the script
// isn't present (local dev, preview deploys without the env), every call here
// is a silent no-op.

type PlausibleFn = (
  event: string,
  options?: { props?: Record<string, string | number | boolean>; callback?: () => void },
) => void;

declare global {
  interface Window {
    plausible?: PlausibleFn & { q?: unknown[] };
  }
}

/**
 * Cloud conversion funnel. Observable browser/workspace transitions only.
 * A purely local `burnlens scan` is never sent here.
 *
 * Activation metric: workspace reached first useful shared economics view
 * (`economics_visible`), not downloads or local scans.
 */
export const FUNNEL = {
  LANDING_VIEW: "landing_view",
  SCAN_DOCS_VIEW: "scan_docs_view",
  AGENCY_LANDING_VIEW: "agency_landing_view",
  INSTALL_COPY: "install_copy",
  CLOUD_CONNECT_STARTED: "cloud_connect_started",
  WORKSPACE_CREATED: "workspace_created",
  FIRST_SYNC: "first_sync",
  ECONOMICS_VISIBLE: "economics_visible",
  TEAMMATE_INVITED: "teammate_invited",
  SECOND_ACTIVE_DAY: "second_active_day",
  TRIAL_STARTED: "trial_started",
  SUBSCRIPTION_STARTED: "subscription_started",
  RENEWED: "renewed",
} as const;

export function trackEvent(
  name: string,
  props?: Record<string, string | number | boolean>,
): void {
  if (typeof window === "undefined") return;
  const p = window.plausible;
  if (typeof p !== "function") return;
  try {
    p(name, props ? { props } : undefined);
  } catch {
    // analytics must never break the app
  }
}
