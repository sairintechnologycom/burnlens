import type { ProviderConcentration } from "@/lib/contracts";
import { formatUsd } from "./OutcomesTable";

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export function ConcentrationTable({ rows }: { rows: ProviderConcentration[] }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Provider</th>
          <th>Spend</th>
          <th>Spend share</th>
          <th>Accepted outcomes</th>
          <th>Outcome share</th>
          <th>Workflows</th>
          <th>Sole provider on</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.provider}>
            <td><span className="tag tag-feature">{r.provider}</span></td>
            <td>${formatUsd(r.spend_usd)}</td>
            <td>{pct(r.spend_share)}</td>
            <td>{r.accepted_outcomes.toLocaleString()}</td>
            <td>{pct(r.accepted_share)}</td>
            <td>{r.workflows.toLocaleString()}</td>
            {/* The dependency number: workflows where nothing else has been
                shown to do the work. Amber whenever it is not zero. */}
            <td className={r.sole_provider_workflows > 0 ? "amber" : undefined}>
              {r.sole_provider_workflows.toLocaleString()}
              {r.sole_provider_workflows > 0 ? ` of ${r.workflows}` : ""}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
