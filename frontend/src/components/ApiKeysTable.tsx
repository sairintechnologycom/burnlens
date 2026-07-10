"use client";
import { useState } from "react";

import { formatDate, formatRelativeTime } from "@/lib/format";

import EditKeyLabelInline from "./EditKeyLabelInline";

export interface ApiKeyRow {
  id: string;
  name: string;
  last4: string;
  created_at: string;
  revoked_at: string | null;
  paused_at: string | null;
  last_used_at: string | null;
}

interface ApiKeysTableProps {
  keys: ApiKeyRow[];
  onRequestRevoke: (key: ApiKeyRow) => void;
  onPause: (key: ApiKeyRow) => Promise<void>;
  onResume: (key: ApiKeyRow) => Promise<void>;
  onSaveLabel: (id: string, newName: string) => Promise<void>;
  canMutateRow: (key: ApiKeyRow) => boolean;
}

function PencilGlyph() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4z" />
    </svg>
  );
}

export default function ApiKeysTable({
  keys,
  onRequestRevoke,
  onPause,
  onResume,
  onSaveLabel,
  canMutateRow,
}: ApiKeysTableProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [actionInFlight, setActionInFlight] = useState<string | null>(null);

  // Active first (created_at DESC), paused next, revoked at bottom (revoked_at DESC)
  const sorted = [...keys].sort((a, b) => {
    const aRev = a.revoked_at ? 2 : a.paused_at ? 1 : 0;
    const bRev = b.revoked_at ? 2 : b.paused_at ? 1 : 0;
    if (aRev !== bRev) return aRev - bRev;
    if (aRev === 2) {
      return (b.revoked_at ?? "").localeCompare(a.revoked_at ?? "");
    }
    return (b.created_at ?? "").localeCompare(a.created_at ?? "");
  });

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr
          style={{
            textAlign: "left",
            color: "var(--muted)",
            fontSize: 12,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
          }}
        >
          <th style={{ padding: "8px 12px", fontWeight: 500 }}>Name</th>
          <th style={{ padding: "8px 12px", fontWeight: 500 }}>Last 4</th>
          <th
            style={{
              padding: "8px 12px",
              fontWeight: 500,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            Last used
          </th>
          <th style={{ padding: "8px 12px", fontWeight: 500 }}>Created</th>
          <th style={{ padding: "8px 12px", fontWeight: 500 }}>Actions</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((k) => {
          const revoked = !!k.revoked_at;
          const editable = !revoked && canMutateRow(k);
          return (
            <tr
              key={k.id}
              style={{
                borderTop: "1px solid var(--border)",
                opacity: revoked ? 0.55 : 1,
              }}
            >
              <td style={{ padding: "10px 12px" }}>
                {editingId === k.id ? (
                  <EditKeyLabelInline
                    initialName={k.name}
                    onSave={async (newName) => {
                      await onSaveLabel(k.id, newName);
                      setEditingId(null);
                    }}
                    onCancel={() => setEditingId(null)}
                  />
                ) : (
                  <span>{k.name}</span>
                )}
              </td>
              <td
                style={{
                  padding: "10px 12px",
                  fontFamily: "var(--font-mono)",
                }}
              >
                ····{k.last4}
              </td>
              <td
                style={{
                  padding: "10px 12px",
                  color: k.last_used_at ? "var(--text)" : "var(--muted)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {formatRelativeTime(k.last_used_at)}
              </td>
              <td style={{ padding: "10px 12px" }}>
                {formatDate(k.created_at)}
              </td>
              <td style={{ padding: "10px 12px" }}>
                {revoked ? (
                  <span style={{ color: "var(--muted)", fontSize: 12 }}>
                    Revoked {formatDate(k.revoked_at!)}
                  </span>
                ) : (
                  <div
                    style={{
                      display: "flex",
                      gap: 8,
                      alignItems: "center",
                    }}
                  >
                    {k.paused_at && (
                      <span style={{ color: "var(--orange)", fontSize: 12, marginRight: 4 }}>
                        Paused
                      </span>
                    )}
                    {editable && (
                      <>
                        {editingId !== k.id && (
                          <button
                            className="btn"
                            type="button"
                            aria-label={`Edit label for ${k.name}`}
                            onClick={() => setEditingId(k.id)}
                            style={{ padding: 4, color: "var(--muted)" }}
                          >
                            <PencilGlyph />
                          </button>
                        )}
                        {k.paused_at ? (
                          <button
                            className="btn btn-cyan"
                            onClick={async () => {
                              setActionInFlight(k.id);
                              await onResume(k);
                              setActionInFlight(null);
                            }}
                            disabled={actionInFlight === k.id}
                            type="button"
                          >
                            Resume
                          </button>
                        ) : (
                          <button
                            className="btn"
                            onClick={async () => {
                              setActionInFlight(k.id);
                              await onPause(k);
                              setActionInFlight(null);
                            }}
                            disabled={actionInFlight === k.id}
                            type="button"
                          >
                            Pause
                          </button>
                        )}
                        <button
                          className="btn btn-red"
                          onClick={() => onRequestRevoke(k)}
                          disabled={actionInFlight === k.id}
                          type="button"
                        >
                          Revoke
                        </button>
                      </>
                    )}
                  </div>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
