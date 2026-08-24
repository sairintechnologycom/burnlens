/** Two-decimal USD, the dashboard's default. Shared so a panel extracted out of
 *  a page does not quietly grow its own formatter and drift from the KPI above it. */
export function formatCost(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
