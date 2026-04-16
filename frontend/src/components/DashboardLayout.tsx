"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Share2,
  TrendingDown,
  Bell,
  Settings,
  LogOut,
  ChevronRight,
  Menu,
  X,
} from "lucide-react";
import { useAuth } from "@/lib/hooks/useAuth";

const NAV_ITEMS = [
  { href: "/dashboard",      icon: LayoutDashboard, label: "Overview" },
  { href: "/connections",    icon: Share2,           label: "Connections" },
  { href: "/optimizations",  icon: TrendingDown,     label: "Optimizations" },
  { href: "/alerts",         icon: Bell,             label: "Alerts" },
  { href: "/settings",       icon: Settings,         label: "Settings" },
];

function NavItem({ href, icon: Icon, label, onClick }: { href: string; icon: any; label: string; onClick?: () => void }) {
  const pathname = usePathname();
  const isActive = pathname === href;
  return (
    <Link
      href={href}
      onClick={onClick}
      className="sidebar-nav-item"
      style={isActive ? {
        background: "var(--primary-glow)",
        color: "var(--primary)",
        border: "1px solid rgba(116,212,165,0.18)",
      } : {}}
    >
      <Icon size={17} style={{ flexShrink: 0 }} />
      <span style={{ fontSize: 14, fontWeight: 500 }}>{label}</span>
      {isActive && <ChevronRight size={13} style={{ marginLeft: "auto", opacity: 0.45 }} />}
    </Link>
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { session, loading, logout } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  if (loading || !session) {
    return (
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        background: "var(--background)",
      }}>
        <div style={{
          width: 32, height: 32,
          border: "2px solid rgba(116,212,165,0.2)",
          borderTopColor: "var(--primary)",
          borderRadius: "50%",
          animation: "spin 0.8s linear infinite",
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  return (
    <div className="dashboard-container">

      {/* ── Desktop Sidebar ── */}
      <aside className="desktop-sidebar">
        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 6px", marginBottom: 40 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 9,
            background: "linear-gradient(135deg, var(--accent), var(--primary))",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 17, fontWeight: 700, color: "var(--background)", flexShrink: 0,
          }}>⊡</div>
          <span style={{ color: "#fff", fontWeight: 700, fontSize: 18, letterSpacing: "-0.02em" }}>BurnLens</span>
        </div>

        {/* Nav */}
        <nav style={{ flex: 1 }}>
          {NAV_ITEMS.map((item) => (
            <NavItem key={item.href} {...item} />
          ))}
        </nav>

        {/* Footer */}
        <div style={{ borderTop: "1px solid var(--card-border)", paddingTop: 20, marginTop: "auto" }}>
          <div style={{ padding: "0 8px", marginBottom: 12 }}>
            <p style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", fontFamily: "var(--font-mono)", letterSpacing: "0.06em", marginBottom: 4 }}>Organization</p>
            <p style={{ fontSize: 14, color: "#fff", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{session.orgName}</p>
          </div>
          <button
            onClick={logout}
            style={{
              display: "flex", alignItems: "center", gap: 10,
              width: "100%", padding: "10px 14px", borderRadius: 10,
              background: "none", border: "none",
              color: "var(--muted)", fontSize: 14, fontWeight: 500,
              cursor: "pointer", transition: "color 0.2s, background 0.2s",
              fontFamily: "var(--font-sans)",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = "#f87171"; e.currentTarget.style.background = "rgba(248,113,113,0.06)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = "var(--muted)"; e.currentTarget.style.background = "none"; }}
          >
            <LogOut size={17} />
            Sign Out
          </button>
        </div>
      </aside>

      {/* ── Main Area ── */}
      <main className="main-content">
        {/* Header */}
        <header className="glass" style={{
          height: 60, borderBottom: "1px solid var(--card-border)",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "0 32px", position: "sticky", top: 0, zIndex: 40,
        }}>
          {/* Mobile menu btn */}
          <button
            className="mobile-menu-btn"
            onClick={() => setMobileMenuOpen(true)}
          >
            <Menu size={20} />
          </button>

          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, color: "var(--muted)" }}>
            <span style={{ opacity: 0.5 }}>Dashboard</span>
            <ChevronRight size={12} style={{ opacity: 0.3 }} />
            <span style={{ color: "#fff", fontWeight: 500 }}>{session.orgName}</span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <span className="pill" style={{ fontSize: 10 }}>Free Tier</span>
            <div style={{
              width: 32, height: 32, borderRadius: "50%",
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.1)",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--muted)", fontSize: 14, fontWeight: 600,
            }}>
              {session.orgName[0].toUpperCase()}
            </div>
          </div>
        </header>

        {/* Page content */}
        <div className="content-padding">
          {children}
        </div>
      </main>

      {/* ── Mobile Drawer ── */}
      {mobileMenuOpen && (
        <div style={{ position: "fixed", inset: 0, zIndex: 50 }}>
          <div
            style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.65)", backdropFilter: "blur(4px)" }}
            onClick={() => setMobileMenuOpen(false)}
          />
          <aside style={{
            position: "absolute", top: 0, left: 0, bottom: 0, width: 260,
            background: "var(--background)", borderRight: "1px solid var(--card-border)",
            padding: 24, boxShadow: "4px 0 32px rgba(0,0,0,0.4)", display: "flex", flexDirection: "column",
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 36 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{
                  width: 30, height: 30, borderRadius: 8,
                  background: "linear-gradient(135deg, var(--accent), var(--primary))",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 16, fontWeight: 700, color: "var(--background)",
                }}>⊡</div>
                <span style={{ color: "#fff", fontWeight: 700, fontSize: 17 }}>BurnLens</span>
              </div>
              <button onClick={() => setMobileMenuOpen(false)} style={{ background: "none", border: "none", color: "var(--muted)", cursor: "pointer", padding: 6 }}>
                <X size={20} />
              </button>
            </div>

            <nav style={{ flex: 1 }}>
              {NAV_ITEMS.map((item) => (
                <NavItem key={item.href} {...item} onClick={() => setMobileMenuOpen(false)} />
              ))}
            </nav>

            <div style={{ borderTop: "1px solid var(--card-border)", paddingTop: 20 }}>
              <button
                onClick={logout}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  width: "100%", padding: "10px 14px", borderRadius: 10,
                  background: "none", border: "none",
                  color: "var(--muted)", fontSize: 14, fontWeight: 500,
                  cursor: "pointer", fontFamily: "var(--font-sans)",
                }}
              >
                <LogOut size={17} />
                Sign Out
              </button>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
