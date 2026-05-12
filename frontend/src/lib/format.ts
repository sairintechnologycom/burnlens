/**
 * Date / time helpers used across the dashboard.
 *
 * Phase 16 (D-08, UI-SPEC §Last-used column): formatRelativeTime cascades
 * from "Just now" up to absolute date at ≥30d. No external dep — UI-SPEC
 * forbids date-fns / dayjs.
 */

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "Never used";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "Never used";
  const s = Math.floor(ms / 1000);
  if (s < 60) return "Just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d} day${d === 1 ? "" : "s"} ago`;
  if (d < 30) {
    const w = Math.floor(d / 7);
    return `${w} week${w === 1 ? "" : "s"} ago`;
  }
  return formatDate(iso); // absolute fallback so we never say "47 weeks ago"
}
