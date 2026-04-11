"use client";

import { useEffect, useState, useCallback } from "react";
import DashboardLayout from "@/components/DashboardLayout";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  AreaChart,
  Area,
  Cell
} from "recharts";
import { 
  DollarSign, 
  Cpu, 
  Zap, 
  RefreshCw, 
  Plus,
  AlertTriangle,
  ArrowUpRight,
  TrendingDown,
  Globe,
  Layers,
  Clock
} from "lucide-react";
import Link from "next/link";
import { motion } from "framer-motion";

interface SummaryData {
  total_cost: number;
  total_tokens: number;
  total_calls: number;
  by_provider: any[];
  by_model: any[];
}

interface TimeseriesPoint {
  date: string;
  provider: string;
  cost: number;
  tokens: number;
  calls: number;
}

interface OptimizationData {
  monthly_savings: number;
}

const COLORS = ["#74D4A5", "#D4A574", "#74A5D4", "#A574D4", "#f43f5e"];

export default function Dashboard() {
  const { session, logout } = useAuth();
  const [data, setData] = useState<SummaryData | null>(null);
  const [timeseries, setTimeseries] = useState<any[]>([]);
  const [totalSavings, setTotalSavings] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [lastSynced, setLastSynced] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!session) return;
    try {
      const [summary, ts, opts] = await Promise.all([
        apiFetch("/api/v1/usage/summary?days=30", session.apiKey),
        apiFetch("/api/v1/usage/timeseries?days=30", session.apiKey).catch(() => []),
        apiFetch("/api/v1/optimizations", session.apiKey).catch(() => []),
      ]);
      setData(summary);

      // Aggregate timeseries by date (merge providers)
      const byDate: Record<string, { date: string; cost: number; tokens: number; calls: number }> = {};
      (ts as TimeseriesPoint[]).forEach((p) => {
        if (!byDate[p.date]) {
          byDate[p.date] = { date: p.date, cost: 0, tokens: 0, calls: 0 };
        }
        byDate[p.date].cost += p.cost;
        byDate[p.date].tokens += p.tokens;
        byDate[p.date].calls += p.calls;
      });
      const sortedTs = Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date));
      // Format dates for display
      setTimeseries(sortedTs.map(d => ({
        ...d,
        label: new Date(d.date + "T00:00:00").toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      })));

      // Calculate real savings from optimizations
      const savings = (opts as OptimizationData[]).reduce((sum: number, o: any) => sum + (o.monthly_savings || 0), 0);
      setTotalSavings(savings);

      setLastSynced(new Date());
    } catch (err: any) {
      if (err instanceof AuthError) {
        logout();
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh every 60 seconds
  useEffect(() => {
    document.title = "Dashboard | BurnLens";
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleSync = async () => {
    if (!session) return;
    setSyncing(true);
    try {
      await apiFetch("/api/v1/sync", session.apiKey, { method: "POST" });
      setTimeout(fetchData, 2000); 
    } catch (err: any) {
      alert("Sync failed: " + err.message);
    } finally {
      setSyncing(false);
    }
  };

  const handleSeed = async () => {
    if (!session) return;
    setSeeding(true);
    try {
      await apiFetch("/api/v1/debug/seed", session.apiKey, { method: "POST" });
      await fetchData();
    } catch (err: any) {
      alert("Seed failed: " + err.message);
    } finally {
      setSeeding(false);
    }
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          <div className="animate-pulse" style={{ height: 40, width: 192, background: "rgba(255,255,255,0.05)", borderRadius: 8 }} />
          <div className="md-grid-3" style={{ gap: 24 }}>
            <div className="animate-pulse" style={{ height: 128, background: "rgba(255,255,255,0.05)", borderRadius: 16 }} />
            <div className="animate-pulse" style={{ height: 128, background: "rgba(255,255,255,0.05)", borderRadius: 16 }} />
            <div className="animate-pulse" style={{ height: 128, background: "rgba(255,255,255,0.05)", borderRadius: 16 }} />
          </div>
          <div className="animate-pulse" style={{ height: 384, background: "rgba(255,255,255,0.05)", borderRadius: 16 }} />
        </div>
      </DashboardLayout>
    );
  }

  const providerData = data?.by_provider.map((p: any, i: number) => ({
    name: p.provider.charAt(0).toUpperCase() + p.provider.slice(1),
    value: p.total_cost,
    color: COLORS[i % COLORS.length]
  })) || [];

  return (
    <DashboardLayout>
      <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
        {/* ── Header ── */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h1 className="text-3xl font-bold text-white tracking-tight">Overview</h1>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 4 }}>
              <p className="text-muted text-sm">Usage and spend analysis for the last 30 days.</p>
              {lastSynced && (
                <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "rgba(255,255,255,0.25)", fontFamily: "var(--font-mono)" }}>
                  <Clock size={10} />
                  Updated {lastSynced.toLocaleTimeString()}
                </span>
              )}
            </div>
          </div>
          
          <div style={{ display: "flex", gap: 12 }}>
            <button 
              onClick={handleSync}
              disabled={syncing}
              className="btn btn-primary"
              style={{ padding: "0 20px", height: 40 }}
            >
              <RefreshCw size={16} className={syncing ? "animate-spin" : ""} style={{ marginRight: 8 }} />
              {syncing ? "Syncing..." : "Sync Now"}
            </button>
            <button 
              onClick={handleSeed}
              disabled={seeding}
              className="btn"
              style={{ padding: "0 20px", height: 40, borderColor: "var(--accent)", color: "var(--accent)" }}
            >
              <RefreshCw size={16} className={seeding ? "animate-spin" : ""} style={{ marginRight: 8 }} />
              {seeding ? "Seeding..." : "Seed Demo Data"}
            </button>
            <Link href="/connections" className="btn" style={{ padding: "0 20px", height: 40 }}>
              <Plus size={16} style={{ marginRight: 8 }} />
              Add Connection
            </Link>
          </div>
        </div>

        {/* ── Totals Grid ── */}
        <div className="md-grid-3" style={{ gap: 24 }}>
          <motion.div 
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="card"
            style={{ background: "rgba(116,212,165,0.05)", borderColor: "rgba(116,212,165,0.1)" }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
              <div style={{ width: 40, height: 40, borderRadius: 12, background: "rgba(116,212,165,0.1)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--primary)" }}>
                <DollarSign size={20} />
              </div>
              <span style={{ color: "var(--muted)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "var(--font-mono)" }}>Monthly Spend</span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span className="text-3xl font-bold text-white font-mono">
                ${data?.total_cost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>
          </motion.div>

          <motion.div 
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="card"
          >
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
              <div style={{ width: 40, height: 40, borderRadius: 12, background: "rgba(59,130,246,0.1)", display: "flex", alignItems: "center", justifyContent: "center", color: "#60a5fa" }}>
                <Cpu size={20} />
              </div>
              <span style={{ color: "var(--muted)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "var(--font-mono)" }}>Total Tokens</span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span className="text-3xl font-bold text-white font-mono">
                {(data?.total_tokens || 0).toLocaleString()}
              </span>
            </div>
          </motion.div>

          <motion.div 
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="card"
          >
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
              <div style={{ width: 40, height: 40, borderRadius: 12, background: "rgba(249,115,22,0.1)", display: "flex", alignItems: "center", justifyContent: "center", color: "#fb923c" }}>
                <Zap size={20} />
              </div>
              <span style={{ color: "var(--muted)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "var(--font-mono)" }}>API Calls</span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span className="text-3xl font-bold text-white font-mono">
                {(data?.total_calls || 0).toLocaleString()}
              </span>
            </div>
          </motion.div>
        </div>

        {/* ── Spend Trend (Timeseries) ── */}
        {timeseries.length > 0 && (
          <div className="card" style={{ display: "flex", flexDirection: "column", height: 320 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
              <h3 className="text-white font-semibold" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <TrendingDown size={18} style={{ color: "var(--muted)" }} />
                Daily Spend Trend
              </h3>
              <span style={{ fontSize: 10, color: "var(--muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Last 30 Days</span>
            </div>
            <div style={{ flex: 1, width: "100%" }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={timeseries} margin={{ top: 0, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorCost" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#74D4A5" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="#74D4A5" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.05)" />
                  <XAxis 
                    dataKey="label" 
                    axisLine={false} 
                    tickLine={false} 
                    tick={{ fill: "#666", fontSize: 10 }} 
                    dy={10}
                    interval="preserveStartEnd"
                  />
                  <YAxis 
                    axisLine={false} 
                    tickLine={false} 
                    tick={{ fill: "#666", fontSize: 10 }}
                    tickFormatter={(val) => `$${val}`}
                  />
                  <Tooltip 
                    cursor={{ stroke: "rgba(116,212,165,0.2)" }}
                    contentStyle={{ 
                      background: "#08080f", 
                      border: "1px solid rgba(255,255,255,0.1)", 
                      borderRadius: "12px",
                      fontSize: "12px"
                    }}
                    formatter={(value: any) => [`$${Number(value || 0).toFixed(2)}`, "Spend"]}
                    labelFormatter={(label) => label}
                  />
                  <Area 
                    type="monotone" 
                    dataKey="cost" 
                    stroke="#74D4A5" 
                    strokeWidth={2}
                    fillOpacity={1} 
                    fill="url(#colorCost)" 
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* ── Charts & Table ── */}
        <div className="lg-grid-2" style={{ gap: 32 }}>
          {/* Spend by Provider */}
          <div className="card" style={{ display: "flex", flexDirection: "column", height: 400 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 32 }}>
              <h3 className="text-white font-semibold" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Globe size={18} style={{ color: "var(--muted)" }} />
                Spend by Provider
              </h3>
            </div>
            {providerData.length > 0 ? (
              <div style={{ flex: 1, width: "100%" }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={providerData} margin={{ top: 0, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.05)" />
                    <XAxis 
                      dataKey="name" 
                      axisLine={false} 
                      tickLine={false} 
                      tick={{ fill: "#666", fontSize: 11 }} 
                      dy={10}
                    />
                    <YAxis 
                      axisLine={false} 
                      tickLine={false} 
                      tick={{ fill: "#666", fontSize: 11 }}
                      tickFormatter={(val) => `$${val}`}
                    />
                    <Tooltip 
                      cursor={{ fill: "rgba(255,255,255,0.03)" }}
                      contentStyle={{ 
                        background: "#08080f", 
                        border: "1px solid rgba(255,255,255,0.1)", 
                        borderRadius: "12px",
                        fontSize: "12px"
                      }}
                    />
                    <Bar dataKey="value" radius={[6, 6, 0, 0]} barSize={40}>
                      {providerData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: 32, border: "1px dashed rgba(255,255,255,0.05)", borderRadius: 16 }}>
                <AlertTriangle size={32} style={{ color: "var(--muted)", marginBottom: 16, opacity: 0.2 }} />
                <p className="text-sm text-muted">No provider data yet. Connect an account to see your spend breakdown.</p>
              </div>
            )}
          </div>

          {/* Spend by Model */}
          <div className="card" style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 32 }}>
              <h3 className="text-white font-semibold" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Layers size={18} style={{ color: "var(--muted)" }} />
                Top Models
              </h3>
              <p style={{ fontSize: 10, color: "var(--muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Cost Ranking</p>
            </div>
            
            <div style={{ flex: 1, overflow: "auto" }}>
              {data?.by_model.length ? (
                <table style={{ width: "100%", textAlign: "left", fontSize: 14 }}>
                  <thead>
                    <tr style={{ color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "var(--font-mono)", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                      <th style={{ paddingBottom: 16, fontWeight: 500 }}>Model</th>
                      <th style={{ paddingBottom: 16, fontWeight: 500 }}>Calls</th>
                      <th style={{ paddingBottom: 16, fontWeight: 500, textAlign: "right" }}>Cost</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {data.by_model.slice(0, 7).map((m: any, i: number) => (
                      <tr key={i} style={{ transition: "background 0.2s" }} onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.01)"} onMouseLeave={(e) => e.currentTarget.style.background = "none"}>
                        <td style={{ padding: "16px 0" }}>
                          <div style={{ display: "flex", flexDirection: "column" }}>
                            <span style={{ color: "#fff", fontWeight: 500 }}>{m.model}</span>
                            <span style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>{m.provider}</span>
                          </div>
                        </td>
                        <td style={{ padding: "16px 0", color: "var(--muted)", fontFamily: "var(--font-mono)" }}>{m.api_calls.toLocaleString()}</td>
                        <td style={{ padding: "16px 0", textAlign: "right" }}>
                          <span style={{ color: "#fff", fontWeight: 700, fontFamily: "var(--font-mono)" }}>${m.total_cost.toFixed(2)}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: 32, border: "1px dashed rgba(255,255,255,0.05)", borderRadius: 16 }}>
                  <AlertTriangle size={32} style={{ color: "var(--muted)", marginBottom: 16, opacity: 0.2 }} />
                  <p className="text-sm text-muted">Waiting for usage records...</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Optimization Opportunities ── */}
        <div className="card" style={{ background: "rgba(212,165,116,0.05)", borderColor: "rgba(212,165,116,0.1)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: "rgba(212,165,116,0.1)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)" }}>
                <TrendingDown size={18} />
              </div>
              <h3 className="text-white font-bold tracking-tight">Optimization Opportunities</h3>
            </div>
            <Link href="/optimizations" style={{ color: "var(--accent)", fontSize: 12, fontWeight: 600, display: "flex", alignItems: "center", gap: 4 }}>
              View All <ArrowUpRight size={14} />
            </Link>
          </div>
          <p className="text-sm text-muted" style={{ marginBottom: 16 }}>
            {totalSavings > 0
              ? "Our engine identified several ways to cut your bill based on recent patterns."
              : "Connect providers and seed data to unlock optimization recommendations."
            }
          </p>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span className="text-2xl font-bold text-white font-mono">
              ${totalSavings.toFixed(2)}
            </span>
            <span style={{ color: "var(--muted)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "var(--font-mono)" }}>Estimated Monthly Savings</span>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
