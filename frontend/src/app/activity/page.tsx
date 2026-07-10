"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */


import { useEffect, useState, useCallback } from "react";
import { History, Undo2 } from "lucide-react";
import Shell from "@/components/Shell";
import EmptyState from "@/components/EmptyState";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";

interface ActivityEntry {
  id: string;
  action: string;
  detail: any;
  created_at: string;
  user_email?: string;
}

function ActivityContent() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();

  const [entries, setEntries] = useState<ActivityEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [undoing, setUndoing] = useState<string | null>(null);

  const fetchActivity = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch("/api/v1/team/activity", session.token);
      setEntries(Array.isArray(data.entries) ? data.entries : []);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => {
    document.title = "Activity Log | BurnLens";
    fetchActivity();
  }, [fetchActivity]);

  const handleUndo = async (entry: ActivityEntry) => {
    if (!session || undoing) return;
    
    // Determine the undo action based on the original action
    let undoAction = "";
    let confirmMsg = "";
    
    if (entry.action === "action_pause_api_key") {
      undoAction = "unpause_api_key";
      confirmMsg = "Unpause this API key?";
    } else if (entry.action === "action_increase_budget") {
      undoAction = "revert_budget";
      confirmMsg = "Revert budget override?";
    } else if (entry.action === "action_downgrade_model") {
      undoAction = "revert_downgrade";
      confirmMsg = "Revert model downgrade?";
    }
    
    if (!undoAction) {
      showToast("This action cannot be undone automatically", "info");
      return;
    }
    
    if (!confirm(confirmMsg)) return;
    
    setUndoing(entry.id);
    try {
      // We'll need to implement these 'undo' endpoints or a generic undo
      // For now, I'll simulate or use the existing actions with 'revert' logic
      await apiFetch(`/api/v1/actions/revert`, session.token, {
        method: "POST",
        body: JSON.stringify({ original_activity_id: entry.id, action: undoAction }),
      });
      showToast("Action reverted", "success");
      fetchActivity();
    } catch (err: any) {
      showToast("Failed to revert action: " + err.message, "error");
    } finally {
      setUndoing(null);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <div className="card">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton" style={{ height: 48, marginBottom: 8 }} />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <span className="error-inline" onClick={fetchActivity}>
          Couldn&apos;t load activity log — retry &#x2197;
        </span>
      </div>
    );
  }

  const formatAction = (action: string) => {
    return action.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
  };

  const formatDate = (iso: string) => {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  };

  return (
    <div>
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Workspace Activity</span>
        </div>

        {entries.length === 0 ? (
          <EmptyState
            title="No activity recorded"
            description="All configuration changes and automated actions will appear here."
          />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Action</th>
                <th>Detail</th>
                <th>User</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td style={{ fontSize: 12, color: "var(--muted)" }}>
                    {formatDate(entry.created_at)}
                  </td>
                  <td>
                    <span className="provider-badge" style={{ 
                      background: entry.action.startsWith("action_") ? "rgba(224,120,64,0.1)" : "var(--bg3)",
                      color: entry.action.startsWith("action_") ? "var(--cyan)" : "var(--text)"
                    }}>
                      {formatAction(entry.action)}
                    </span>
                  </td>
                  <td style={{ fontSize: 12, maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {JSON.stringify(entry.detail)}
                  </td>
                  <td style={{ fontSize: 12 }}>
                    {entry.user_email || "System"}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {entry.action.startsWith("action_") && (
                      <button
                        className="btn btn-ghost"
                        title="Revert this action"
                        onClick={() => handleUndo(entry)}
                        disabled={undoing === entry.id}
                      >
                        <Undo2 size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default function ActivityPage() {
  return (
    <Shell>
      <ActivityContent />
    </Shell>
  );
}
