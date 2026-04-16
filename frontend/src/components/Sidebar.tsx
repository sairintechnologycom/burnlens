"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface SidebarItem {
  href: string;
  label: string;
  badge?: { count: number; color: "red" | "green" | "amber" };
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
      { href: "/teams", label: "By team" },
      { href: "/customers", label: "By customer" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { href: "/waste", label: "Waste alerts", badge: { count: 3, color: "red" } },
      { href: "/savings", label: "Savings", badge: { count: 2, color: "green" } },
      { href: "/budgets", label: "Budgets", badge: { count: 1, color: "amber" } },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/connections", label: "Connections" },
      { href: "/settings", label: "Settings" },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sidebar">
      {GROUPS.map((group) => (
        <div key={group.label} className="sidebar-group">
          <div className="sidebar-label">{group.label}</div>
          {group.items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`sidebar-item ${pathname === item.href ? "active" : ""}`}
            >
              {item.label}
              {item.badge && (
                <span className={`sidebar-badge ${item.badge.color}`}>
                  {item.badge.count}
                </span>
              )}
            </Link>
          ))}
        </div>
      ))}
    </aside>
  );
}
