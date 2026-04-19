"use client";

import React, { useState } from "react";
import { PeriodProvider } from "@/lib/contexts/PeriodContext";
import { BillingProvider } from "@/lib/contexts/BillingContext";
import { useAuth } from "@/lib/hooks/useAuth";
import Topbar from "./Topbar";
import Sidebar from "./Sidebar";
import RightPanel from "./RightPanel";

export default function Shell({ children }: { children: React.ReactNode }) {
  const { session, loading } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  if (loading || !session) {
    return (
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        background: "var(--bg)",
      }}>
        <div className="skeleton" style={{ width: 32, height: 32, borderRadius: "50%" }} />
      </div>
    );
  }

  return (
    <PeriodProvider>
      <BillingProvider>
        <div className="shell">
          <Topbar />
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
