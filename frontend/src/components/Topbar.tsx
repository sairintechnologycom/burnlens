"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "./ThemeProvider";
import { usePeriod } from "@/lib/contexts/PeriodContext";

const NAV_LINKS = [
  { href: "/dashboard", label: "Overview" },
  { href: "/models", label: "Models" },
  { href: "/teams", label: "Teams" },
  { href: "/customers", label: "Customers" },
  { href: "/waste", label: "Alerts" },
  { href: "/settings", label: "Settings" },
];

const PERIODS = ["7d", "30d", "90d"] as const;

function LogoSVG() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
      <circle cx="10" cy="10" r="8" stroke="var(--cyan)" strokeWidth="1.5" />
      <circle cx="10" cy="10" r="5" stroke="var(--cyan)" strokeWidth="1.2" />
      <circle cx="10" cy="10" r="2" fill="var(--cyan)" />
      <path d="M 10 2 A 8 8 0 0 1 18 10" stroke="var(--amber)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export default function Topbar() {
  const pathname = usePathname();
  const { theme, toggle } = useTheme();
  const { period, setPeriod } = usePeriod();

  return (
    <div className="topbar">
      <div className="topbar-left">
        <LogoSVG />
        <span className="topbar-logo-text">
          BURN<em>LENS</em>
        </span>
      </div>

      <div className="topbar-center">
        {NAV_LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={`topbar-link ${pathname === link.href ? "active" : ""}`}
          >
            {link.label}
          </Link>
        ))}
      </div>

      <div className="topbar-right">
        <div className="live-pill">
          <span className="live-dot" />
          LIVE
        </div>

        <div style={{ display: "flex", gap: 2 }}>
          {PERIODS.map((p) => (
            <button
              key={p}
              className={`period-btn ${period === p ? "active" : ""}`}
              onClick={() => setPeriod(p)}
            >
              {p}
            </button>
          ))}
        </div>

        <button className="theme-toggle" onClick={toggle}>
          {theme === "dark" ? "\u2600" : "\u263E"}
        </button>
      </div>
    </div>
  );
}
