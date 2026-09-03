import Link from "next/link";

/** The four pages of one economics model. Engines stay on their routes. */
export const ECONOMICS_PAGES = [
  { href: "/dashboard", label: "Overview" },
  { href: "/outcomes", label: "Outcomes" },
  { href: "/savings", label: "Savings" },
  { href: "/waste", label: "Waste" },
] as const;

export function EconomicsNav({ current }: { current: string }) {
  return (
    <nav
      aria-label="Economics"
      style={{
        display: "flex",
        gap: 4,
        padding: "8px 16px 0",
        fontSize: 13,
        borderBottom: "1px solid var(--border)",
      }}
    >
      {ECONOMICS_PAGES.map((item) => {
        const active = current === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            style={{
              padding: "8px 10px",
              color: active ? "var(--text)" : "var(--muted)",
              fontWeight: active ? 600 : 400,
              borderBottom: active
                ? "2px solid var(--cyan)"
                : "2px solid transparent",
              textDecoration: "none",
            }}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
