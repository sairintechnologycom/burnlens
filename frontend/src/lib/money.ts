/** Two-decimal USD, the dashboard's default. Shared so a panel extracted out of
 *  a page does not quietly grow its own formatter and drift from the KPI above it. */
export function formatCost(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Request-row money. Unpriced is not a measured zero. */
export function formatRequestCostUsd(
  costUsd: number | null | undefined,
  pricingClass: string | null | undefined,
): string {
  if (pricingClass === "unpriced") return "$ unknown";
  return `$${(costUsd ?? 0).toFixed(4)}`;
}
