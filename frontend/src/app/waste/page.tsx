"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import EmptyState from "@/components/EmptyState";
import { apiFetch, AuthError, errorMessageFrom } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";
import type { EconomicsOverview, FindingItem, SavingsVerdict } from "@/lib/contracts";
import { FindingsList } from "./FindingsList";
import { EconomicsNav } from "@/components/EconomicsNav";

function formatUsd(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function KpiStrip({ econ }: { econ: EconomicsOverview }) {
  const accepted =
    econ.cost_per_accepted_usd === null
      ? "—"
      : `$${formatUsd(econ.cost_per_accepted_usd)}`;
  return (
    <div className="stat-strip cols-5">
      <div className="stat-cell">
        <div className="stat-label">Total spend</div>
        <div className="stat-value">${formatUsd(econ.total_spend_usd)}</div>
      </div>
      <div className="stat-cell">
        <div className="stat-label">Detected waste</div>
        <div className="stat-value" style={{ color: "var(--amber)" }}>
          ${formatUsd(econ.detected_waste_usd)}
        </div>
        <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4 }}>
          estimates overlap; not additive
          {econ.waste_estimate_clamped ? " · clamped to 100%" : ""}
        </div>
      </div>
      <div className="stat-cell">
        <div className="stat-label">Waste rate</div>
        <div className="stat-value">{(econ.waste_rate * 100).toFixed(1)}%</div>
      </div>
      <div className="stat-cell" style={{ background: "var(--bg3)" }}>
        <div className="stat-label">Error spend</div>
        <div className="stat-value">${formatUsd(econ.error_spend_usd)}</div>
        <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4 }}>
          {econ.error_request_count} failed request(s) · diagnostic, overlaps waste
        </div>
      </div>
      <div className="stat-cell">
        <div className="stat-label">Cost / accepted</div>
        <div className="stat-value">{accepted}</div>
      </div>
    </div>
  );
}

function WasteContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [econ, setEcon] = useState<EconomicsOverview | null>(null);
  const [findings, setFindings] = useState<FindingItem[]>([]);
  const [verdicts, setVerdicts] = useState<Record<string, SavingsVerdict>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const [e, f, v] = await Promise.all([
        apiFetch(`/api/v1/economics?days=${days}`, session.token),
        apiFetch("/api/v1/findings", session.token),
        apiFetch("/api/v1/findings/verify", session.token).catch(() => []),
      ]);
      setEcon(e as EconomicsOverview);
      setFindings(f as FindingItem[]);
      const byFp: Record<string, SavingsVerdict> = {};
      for (const item of v as SavingsVerdict[]) {
        byFp[item.fingerprint] = item;
      }
      setVerdicts(byFp);
    } catch (err: unknown) {
      if (err instanceof AuthError) logout();
      else if (err instanceof Error) setError(err.message);
      else setError(errorMessageFrom(err, 500));
    } finally {
      setLoading(false);
    }
  }, [session, logout, days]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const onStatus = async (fingerprint: string, status: string) => {
    if (!session) return;
    setPendingId(fingerprint);
    try {
      await apiFetch(`/api/v1/findings/${fingerprint}/status`, session.token, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      await fetchData();
    } catch (err: unknown) {
      if (err instanceof AuthError) logout();
      else if (err instanceof Error) setError(err.message);
      else setError(errorMessageFrom(err, 500));
    } finally {
      setPendingId(null);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        {[1, 2, 3].map((i) => (
          <div key={i} className="skeleton" style={{ height: 80, marginBottom: 8 }} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <span className="error-inline" onClick={fetchData}>
          {error} — retry &#x2197;
        </span>
      </div>
    );
  }

  return (
    <div>
      <EconomicsNav current="/waste" />
      {econ && <KpiStrip econ={econ} />}
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Findings</span>
          <span className="section-header-action">
            {econ ? `${econ.open_finding_count} open` : ""}
          </span>
        </div>
        {findings.length === 0 ? (
          <EmptyState
            title="No waste findings yet"
            description="Findings appear once the hosted dashboard has seen wasteful traffic in the last 7 days. They are also available in the local dashboard via burnlens dashboard."
            code={"burnlens dashboard"}
          />
        ) : (
          <FindingsList
            findings={findings}
            verdicts={verdicts}
            onStatus={onStatus}
            pendingId={pendingId}
          />
        )}
        {/*
          Three of the eight detectors read prompt-segment token counts, which only the
          proxy interceptor computes. Agent logs never record tool schemas at all, so
          `burnlens scan` data cannot produce them — see
          .planning/spike-scan-prompt-segmentation.md. Say so rather than letting a
          scan-only user read the absence as "no waste found".
        */}
        <p
          style={{
            margin: "12px 16px 4px",
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--muted)",
          }}
        >
          Oversized tool schemas, low RAG efficiency and history bloat are only detected
          on traffic routed through the BurnLens proxy. Data imported with{" "}
          <code>burnlens scan</code> has no prompt breakdown to analyse, so those three
          checks stay silent for it.
        </p>
      </div>
    </div>
  );
}

export default function WastePage() {
  return (
    <Shell>
      <WasteContent />
    </Shell>
  );
}
