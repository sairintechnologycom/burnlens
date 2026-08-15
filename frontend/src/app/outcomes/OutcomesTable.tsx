import type { WorkflowEconomics } from "@/lib/contracts";

export function formatUsd(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

export function formatPerAccepted(n: number | null): string {
  return n == null ? "—" : `$${formatUsd(n)}`;
}

export function OutcomesTable({ rows }: { rows: WorkflowEconomics[] }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Workflow</th>
          <th>Accepted</th>
          <th>Rejected / failed</th>
          <th>Total cost</th>
          <th>Rework</th>
          <th>Unattributed</th>
          <th>Per accepted</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.workflow_id}>
            <td><span className="tag tag-feature">{r.workflow_id}</span></td>
            <td>{r.accepted_count.toLocaleString()}</td>
            <td>{(r.rejected_count + r.failed_count).toLocaleString()}</td>
            <td>${formatUsd(r.cost_total_usd)}</td>
            <td>${formatUsd(r.cost_rework_usd)}</td>
            <td>${formatUsd(r.cost_unattributed_usd)}</td>
            <td>{formatPerAccepted(r.cost_per_accepted_usd)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
