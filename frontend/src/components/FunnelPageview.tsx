"use client";

import { useEffect } from "react";
import { trackEvent } from "@/lib/analytics";

/** Fire one named funnel event on mount. Local `burnlens scan` is not observed. */
export function FunnelPageview({ event }: { event: string }) {
  useEffect(() => {
    trackEvent(event);
  }, [event]);
  return null;
}
