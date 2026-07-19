"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useBilling } from "@/lib/contexts/BillingContext";
import { useAuth } from "@/lib/hooks/useAuth";
import { planSatisfies } from "@/lib/hooks/usePlanSatisfies";
import UsageMeter from "./UsageMeter";

interface SidebarItem {
  href: string;
  label: string;
  badge?: { count: number; color: "red" | "green" | "amber" };
  // Phase 10 D-08: minimum plan required to "unlock" this item.
  // The backend require_feature middleware is the authoritative gate;
  // this is purely a UI-affordance hint.
  lockedForPlan?: string;
}

interface SidebarGroup {
  label: string;
  items: SidebarItem[];
}

const GROUPS: SidebarGroup[] = [
  {
    label: "Workspace",
    items: [
      { href: "/dashboard", label: "Overview" },
      { href: "/dashboard/timeline", label: "Cost timeline" },
      { href: "/dashboard/requests", label: "Request log" },
    ],
  },
  {
    label: "Attribution",
    items: [
      { href: "/models", label: "By model" },
      { href: "/features", label: "By feature" },
      // Phase 10 D-09: nav-affordance only — backend middleware is the
      // authoritative gate. Locked items remain clickable (D-10) so the
      // user lands on the teaser page and converts there.
      { href: "/teams", label: "By team", lockedForPlan: "teams" },
      { href: "/customers", label: "By customer", lockedForPlan: "teams" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { href: "/waste", label: "Waste alerts" },
      { href: "/savings", label: "Savings" },
      { href: "/budgets", label: "Budgets" },
      { href: "/alerts", label: "Alerts" },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/api-keys", label: "API Keys" },
      { href: "/activity", label: "Activity Log" },
      { href: "/settings", label: "Settings" },
    ],
  },
];

function LockGlyph() {
  return (
    <svg
      className="sidebar-item-lock-glyph"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="11" width="18" height="11" rx="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

function SignOutGlyph() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}

function KeyGlyph() {
  return (
    <svg
      className="sidebar-item-key-glyph"
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
      <circle cx="8" cy="15" r="4" />
      <path d="M21 2l-9.6 9.6" />
      <path d="M15.5 7.5l3 3L22 7l-3-3" />
    </svg>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const { billing } = useBilling();
  const { session, logout } = useAuth();
  // D-10 fallback chain: prefer the live billing.plan, fall back to the
  // session's plan, then "free" (safest default — locks visible for any
  // unauthenticated/loading render).
  const currentPlan = (
    billing?.plan ??
    session?.plan ??
    "free"
  ).toLowerCase();

  return (
    <aside className="sidebar">
      {GROUPS.map((group) => (
        <div key={group.label} className="sidebar-group">
          <div className="sidebar-label">{group.label}</div>
          {group.items.map((item) => {
            const isLocked =
              !!item.lockedForPlan &&
              !planSatisfies(currentPlan, item.lockedForPlan);
            const planLabel = item.lockedForPlan
              ? item.lockedForPlan.charAt(0).toUpperCase() +
                item.lockedForPlan.slice(1)
              : "";

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`sidebar-item ${pathname === item.href ? "active" : ""} ${isLocked ? "sidebar-item--locked" : ""}`}
                title={
                  isLocked ? `Locked — requires ${planLabel} plan` : undefined
                }
              >
                {isLocked && (
                  <span aria-label={`Locked — requires ${planLabel} plan`}>
                    <LockGlyph />
                  </span>
                )}
                {item.href === "/api-keys" && !isLocked && (
                  <span aria-hidden="true">
                    <KeyGlyph />
                  </span>
                )}
                <span className="sidebar-item-text">
                  <span className="sidebar-item-label">{item.label}</span>
                  {isLocked && (
                    <span className="sidebar-item-sublabel">
                      {planLabel} plan
                    </span>
                  )}
                </span>
                {item.badge && (
                  <span className={`sidebar-badge ${item.badge.color}`}>
                    {item.badge.count}
                  </span>
                )}
              </Link>
            );
          })}
        </div>
      ))}
      <UsageMeter />
      <button type="button" className="sidebar-signout" onClick={logout}>
        <SignOutGlyph />
        <span>Sign out</span>
      </button>
    </aside>
  );
}
