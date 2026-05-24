import Script from "next/script";

// Loads Plausible Analytics only when NEXT_PUBLIC_PLAUSIBLE_DOMAIN is set.
// Uses the `tagged-events` build so click events can be declared via CSS
// classes (e.g. class="plausible-event-name=Get+Started") on any element —
// including server components where we can't attach onClick handlers.
//
// Privacy: Plausible is cookie-free and does not collect personal data, so
// no consent banner is required. See /security for the full data-flow story.

export function PlausibleScript() {
  const domain = process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN;
  if (!domain) return null;

  const src =
    process.env.NEXT_PUBLIC_PLAUSIBLE_SRC ??
    "https://plausible.io/js/script.tagged-events.js";

  return (
    <>
      <Script
        defer
        data-domain={domain}
        src={src}
        strategy="afterInteractive"
      />
      {/* Bootstraps window.plausible() so calls placed before the script
          finishes loading are queued and flushed once it's ready. */}
      <Script id="plausible-init" strategy="afterInteractive">
        {`window.plausible = window.plausible || function() { (window.plausible.q = window.plausible.q || []).push(arguments) }`}
      </Script>
    </>
  );
}
