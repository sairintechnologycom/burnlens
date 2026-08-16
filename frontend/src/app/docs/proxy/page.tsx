import Link from "next/link";
import type { Metadata } from "next";
import { Code, GH, PROVIDERS } from "@/lib/docs";

const TITLE = "Proxy setup and tagging — BurnLens Docs";
const DESCRIPTION =
  "Run the BurnLens proxy on 127.0.0.1:8420, point each provider SDK at it, and attribute every call to a feature, team or customer with three request headers. Includes the providers that expose no base-URL environment variable.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/docs/proxy" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: "https://burnlens.app/docs/proxy",
    siteName: "BurnLens",
    type: "article",
  },
};

export default function DocsProxyPage() {
  return (
    <>
      <h1>Proxy setup and tagging</h1>
      <p className="legal-updated">
        Provider table dumped from the live provider registry on 2026-08-16, not written
        from memory.
      </p>

      <section id="start">
        <h2>Start the proxy</h2>
        <p>
          <code>burnlens start</code> runs a local proxy on <code>127.0.0.1:8420</code>. It
          forwards each request to the real provider — streaming included — and records
          what the call cost on the way through.
        </p>
        <Code>{`burnlens start
burnlens start --port 9000 --host 127.0.0.1
burnlens start --otel        # also export to an OpenTelemetry collector
burnlens start --no-env      # do not print the env var exports on startup`}</Code>
        <p>
          It binds to loopback by default. Exposing it on <code>0.0.0.0</code> puts an
          unauthenticated forwarder holding your provider keys on the network — if you need
          that, put it behind something that authenticates, and read{" "}
          <Link href="/docs/budgets">virtual keys</Link> first.
        </p>
      </section>

      <section id="providers">
        <h2>Point your SDK at it</h2>
        <p>
          Each provider gets its own path. For most, one environment variable is the whole
          integration and your application code does not change at all.
        </p>
        <Code>{`export OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai
export ANTHROPIC_BASE_URL=http://127.0.0.1:8420/proxy/anthropic`}</Code>
        <table className="lp-compare-table">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Proxy path</th>
              <th>SDK environment variable</th>
            </tr>
          </thead>
          <tbody>
            {PROVIDERS.map((p) => (
              <tr key={p.name}>
                <td><strong>{p.name}</strong></td>
                <td><code>{p.path}</code></td>
                <td>{p.env ? <code>{p.env}</code> : <em>none — see below</em>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section id="no-env-var">
        <h2>Google, Mistral and Together have no environment variable</h2>
        <p>
          Their SDKs do not read a base URL from the environment. Setting one does nothing,
          and this failure is silent: your traffic goes straight to the provider while the
          dashboard shows nothing and you conclude BurnLens is broken.
        </p>
        <p>For Google, call the patch helper once at startup, before your first request:</p>
        <Code>{`from burnlens.patch import patch_google
patch_google()`}</Code>
        <p>
          For Mistral and Together, pass the proxy path explicitly where you construct the
          client. The parameter name is the SDK&apos;s, not ours — check yours, it is
          usually <code>base_url</code> or <code>server_url</code>:
        </p>
        <Code>{`client = SomeClient(api_key=..., base_url="http://127.0.0.1:8420/proxy/mistral")`}</Code>
        <p>
          Azure deployment routing and Bedrock bearer-token auth have provider-specific
          detail —{" "}
          <a href={`${GH}/blob/main/docs/PROVIDERS.md`} target="_blank" rel="noreferrer">
            PROVIDERS.md
          </a>{" "}
          covers both. If nothing appears after setup, <code>burnlens doctor</code> checks
          the proxy, the database and provider reachability in one pass.
        </p>
      </section>

      <section id="tags">
        <h2>Attribute spend with tags</h2>
        <p>
          A bill tells you the model. Tags tell you the feature. Three request headers
          attribute any call to any dimension you care about, and BurnLens strips all three
          before the request reaches the provider.
        </p>
        <Code>{`X-BurnLens-Tag-Feature: checkout-summariser
X-BurnLens-Tag-Team: platform
X-BurnLens-Tag-Customer: acme-corp`}</Code>
        <p>
          Set them wherever your SDK lets you add default headers, and every call from that
          client is attributed without further work:
        </p>
        <Code>{`client = OpenAI(default_headers={"X-BurnLens-Tag-Feature": "checkout-summariser"})`}</Code>
        <p>
          Team and customer tags are what per-team budgets and per-customer spend reports
          are keyed on, so tag before you set a budget rather than after.{" "}
          <code>burnlens customers</code> and <code>burnlens budgets</code> read them
          directly.
        </p>
        <p>
          For agent and CI work, <code>burnlens run &lt;command&gt;</code> wraps a child
          process and tags its traffic with the surrounding git context automatically.
        </p>
      </section>

      <section id="privacy">
        <h2>What the proxy sends where</h2>
        <p>
          Request and response bodies go to the provider you were already calling, and
          nowhere else. BurnLens records model, token counts, timing, status and tag values.
          If you enable cloud sync, that metadata — including tag values — is uploaded to
          your workspace; bodies are not, and no setting turns that on.{" "}
          <Link href="/security">How data is handled</Link>.
        </p>
      </section>

      <section id="next">
        <h2>Next</h2>
        <p>
          Metering on its own does not stop anything. To make the proxy refuse a call that
          would breach a limit, see <Link href="/docs/budgets">budgets and hard caps</Link>.
        </p>
      </section>
    </>
  );
}
