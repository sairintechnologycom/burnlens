"use client";

import React, { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { PeriodProvider } from "@/lib/contexts/PeriodContext";
import { BillingProvider } from "@/lib/contexts/BillingContext";
import { useAuth } from "@/lib/hooks/useAuth";
import Topbar from "./Topbar";
import BillingStatusBanner from "./BillingStatusBanner";
import Sidebar from "./Sidebar";
import RightPanel from "./RightPanel";

export default function Shell({ children }: { children: React.ReactNode }) {
  const { session, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Unauth visitors landing on any Shell-wrapped route (dashboard, alerts,
  // budgets, etc.) used to see an infinite skeleton. Send them to /setup
  // with a `next` hint so we can return them here after login.
  useEffect(() => {
    if (!loading && !session) {
      const next = pathname && pathname !== "/setup" ? `?next=${encodeURIComponent(pathname)}` : "";
      router.replace(`/setup${next}`);
    }
  }, [loading, session, pathname, router]);

  // Close the mobile nav drawer on route change so tapping a link navigates
  // and dismisses the drawer in one action.
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [pathname]);

  if (loading || !session) {
    return (
      <div style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        background: "var(--bg)",
        gap: 16,
      }}>
        <svg width="32" height="32" viewBox="0 0 26 26" fill="none" aria-hidden>
          <circle cx="13" cy="13" r="11.5" stroke="#2a3540" strokeWidth="1" />
          <path d="M13 1.5 A11.5 11.5 0 0 1 24 8" stroke="#f0a928" strokeWidth="1.5" strokeLinecap="round" fill="none" />
          <circle cx="13" cy="13" r="7.5" stroke="#1e2830" strokeWidth="1" />
          <circle cx="13" cy="13" r="2" fill="#00e5c8" />
        </svg>
        <div style={{
          fontFamily: "var(--font-mono), monospace",
          fontSize: 11,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "#6b7785",
        }}>
          {loading ? "Loading BurnLens…" : "Redirecting…"}
        </div>
      </div>
    );
  }

  return (
    <PeriodProvider>
      <BillingProvider>
        <div className="shell">
          <Topbar onMenuClick={() => setMobileMenuOpen(true)} />
          <BillingStatusBanner session={session} />
          <div className="shell-main">
            <Sidebar />
            <main className="shell-content">
              {children}
            </main>
            <RightPanel />
          </div>
        </div>

        {/* Mobile drawer */}
        {mobileMenuOpen && (
          <>
            <div className="mobile-overlay" onClick={() => setMobileMenuOpen(false)} />
            <div className="mobile-drawer">
              <Sidebar />
            </div>
          </>
        )}
      </BillingProvider>
    </PeriodProvider>
  );
}
