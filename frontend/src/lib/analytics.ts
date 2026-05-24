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
