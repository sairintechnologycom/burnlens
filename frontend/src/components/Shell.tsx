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
