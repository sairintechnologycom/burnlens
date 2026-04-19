"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";

type Invoice = {
  id: string;
  billed_at: string | null;
  amount_cents: number | null;
  currency: string | null;
  status: string;
  invoice_pdf_url: string | null;
};

type InvoicesResponse = { invoices: Invoice[] };

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "—";
  }
}

function formatAmount(cents: number | null, currency: string | null): string {
  if (cents === null || cents === undefined) return "—";
  const amount = cents / 100;
  const cur = (currency || "USD").toUpperCase();
  if (cur === "USD") {
    return `$${Number.isInteger(amount) ? amount : amount.toFixed(2)}`;
  }
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: cur,
    }).format(amount);
  } catch {
    return `${amount} ${cur}`;
  }
}

function statusPill(status: string) {
  const s = (status || "").toLowerCase();
  const color =
    s === "paid" || s === "completed"
      ? "var(--cyan)"
      : s === "failed" || s === "canceled"
      ? "var(--red)"
      : "var(--amber)";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 999,
        border: "1px solid var(--border)",
        background: "var(--bg3)",
        fontSize: 10,
        fontWeight: 600,
        color: "var(--text)",
      }}
    >
      <span aria-hidden="true" style={{ color }}>●</span>
      {status || "—"}
    </span>
  );
}

export default function InvoicesCard() {
  const { session, logout } = useAuth();
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const data = (await apiFetch("/billing/invoices", session.token)) as InvoicesResponse;
      setInvoices(Array.isArray(data?.invoices) ? data.invoices.slice(0, 24) : []);
    } catch (err: unknown) {
      if (err instanceof AuthError) {
        logout();
        return;
      }
      setError("Couldn't load invoices");
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div id="invoices" className="card" style={{ margin: 16, marginBottom: 0 }}>
      <div className="section-header">
        <span className="section-header-title" style={{ fontWeight: 600 }}>
          Invoices
        </span>
      </div>
      <div style={{ padding: 16 }}>
        {loading && !invoices && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div className="skeleton" style={{ height: 14, width: "100%", borderRadius: 3 }} />
            <div className="skeleton" style={{ height: 14, width: "88%", borderRadius: 3 }} />
            <div className="skeleton" style={{ height: 14, width: "76%", borderRadius: 3 }} />
          </div>
        )}

        {!loading && error && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 13, color: "var(--muted)" }}>{error}</div>
            <button
              onClick={load}
              style={{
                alignSelf: "flex-start",
                background: "transparent",
                border: "none",
                padding: 0,
                fontSize: 12,
                color: "var(--cyan)",
                textDecoration: "underline",
                cursor: "pointer",
              }}
            >
              Retry
            </button>
          </div>
        )}

        {!loading && !error && invoices && invoices.length === 0 && (
          <div style={{ fontSize: 13, color: "var(--muted)" }}>No invoices yet.</div>
        )}

        {!loading && !error && invoices && invoices.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 13,
              }}
            >
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)", fontSize: 12 }}>
                  <th style={{ padding: "8px 12px", fontWeight: 500 }}>Date</th>
                  <th style={{ padding: "8px 12px", fontWeight: 500 }}>Amount</th>
                  <th style={{ padding: "8px 12px", fontWeight: 500 }}>Status</th>
                  <th style={{ padding: "8px 12px", fontWeight: 500, textAlign: "right" }}>
                    Download PDF
                  </th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((invoice) => (
                  <tr key={invoice.id} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ padding: "10px 12px" }}>{formatDate(invoice.billed_at)}</td>
                    <td style={{ padding: "10px 12px" }}>
                      {formatAmount(invoice.amount_cents, invoice.currency)}
                    </td>
                    <td style={{ padding: "10px 12px" }}>{statusPill(invoice.status)}</td>
                    <td style={{ padding: "10px 12px", textAlign: "right" }}>
                      {invoice.invoice_pdf_url ? (
                        <a
                          href={invoice.invoice_pdf_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: "var(--cyan)", textDecoration: "underline" }}
                        >
                          Download
                        </a>
                      ) : (
                        <span style={{ color: "var(--muted)" }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
