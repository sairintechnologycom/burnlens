"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DOCS_PAGES } from "@/lib/docs";

/**
 * The full docs index, rendered on every docs page. Two jobs: let a reader move
 * between pages without going back to the hub, and give every page a real
 * internal link from every other one.
 */
export default function DocsNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Documentation" style={{ marginTop: 48 }}>
      <h2>All documentation</h2>
      <ul>
        {DOCS_PAGES.map((p) => {
          const current = pathname === p.href;
          return (
            <li key={p.href}>
              {current ? (
                <strong aria-current="page">{p.title}</strong>
              ) : (
                <Link href={p.href}>{p.title}</Link>
              )}{" "}
              — {p.blurb}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
