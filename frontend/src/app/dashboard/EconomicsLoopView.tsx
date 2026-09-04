import Link from "next/link";
import type {
  EconomicsOverview,
  RecommendationRow,
  SavingsRollup,
} from "@/lib/contracts";
import { formatCost } from "@/lib/money";

function formatFine(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

type Tile = {
  href: string;
  label: string;
  value: string;
  hint: string;
};

/** Overview's one-view of the four economics engines. Each tile is a link
 *  to the page that already owns that engine — nothing is recomputed here. */
export function EconomicsLoopPanel({
  econ,
  savings,
  recs,
}: {
  econ: EconomicsOverview | null;
  savings: SavingsRollup | null;
  recs: RecommendationRow[] | null;
}) {
  if (!econ) return null;

  const projected = (recs ?? []).reduce((s, r) => s + r.projected_saving, 0);
  const recCount = recs?.length ?? 0;

  const tiles: Tile[] = [
    {
      href: "/outcomes",
      label: "Outcomes",
      value:
        econ.cost_per_accepted_usd == null
          ? "—"
          : `$${formatCost(econ.cost_per_accepted_usd)}`,
      hint: econ.accepted_count
        ? `${econ.accepted_count.toLocaleString()} accepted`
        : "cost per accepted",
    },
    {
      href: "/savings",
      label: "Verified Savings",
      value: (() => {
        if (!savings) return "—";
        const judged = (savings.counts.verified ?? 0) + (savings.counts.missed ?? 0);
        if (judged === 0 && savings.verified_monthly_usd === 0) {
          return "No verified changes yet";
        }
        return `$${formatFine(savings.verified_monthly_usd)}`;
      })(),
      hint:
        recCount > 0
          ? `${recCount} recommendation${recCount === 1 ? "" : "s"}, $${formatFine(projected)} projected`
          : savings?.realisation_pct == null
            ? "projected is not verified"
            : `${savings.realisation_pct.toFixed(0)}% realised`,
    },
    {
      href: "/waste",
      label: "Waste",
      value: `$${formatFine(econ.detected_waste_usd)}`,
      hint: `${econ.open_finding_count} open finding${econ.open_finding_count === 1 ? "" : "s"}`,
    },
  ];

  return (
    <div className="card" style={{ margin: 16, marginBottom: 0 }}>
      <div className="section-header">
        <span className="section-header-title">Economics</span>
        <span className="section-header-action">same engines as the pages</span>
      </div>
      <div
        className="stat-strip"
        style={{ borderBottom: "none", gridTemplateColumns: "repeat(3, 1fr)" }}
      >
        {tiles.map((t) => (
          <Link
            key={t.label}
            href={t.href}
            className="stat-cell"
            style={{ textDecoration: "none", color: "inherit" }}
          >
            <div className="stat-label">{t.label}</div>
            <div className="stat-value">{t.value}</div>
            <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4 }}>
              {t.hint}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
