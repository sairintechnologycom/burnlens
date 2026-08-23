import Link from "next/link";
import type { Metadata } from "next";
import pricing from "@/data/llm-pricing.json";

const COUNT = pricing.model_count;
const PROVIDER_COUNT = pricing.providers.length;

export const metadata: Metadata = {
  title: "LLM API Pricing — Every Model, Every Provider (2026)",
  description:
    `Input, output and prompt-cache rates per million tokens for ${COUNT} models across OpenAI, Anthropic, Google, Bedrock, Groq, Mistral, Together, xAI and DeepSeek. The same table BurnLens bills from.`,
  alternates: { canonical: "/llm-pricing" },
  openGraph: {
    title: "LLM API Pricing — Every Model, Every Provider",
    description:
      `Input, output and cache rates per million tokens for ${COUNT} models across ${PROVIDER_COUNT} providers — the same pricing table the BurnLens proxy bills from.`,
    url: "https://burnlens.app/llm-pricing",
    siteName: "BurnLens",
    type: "article",
  },
  twitter: {
    card: "summary_large_image",
    title: "LLM API Pricing — Every Model, Every Provider",
    description:
      `Input, output and cache rates per million tokens for ${COUNT} models across ${PROVIDER_COUNT} providers.`,
  },
};

// Only the display label differs from the pricing_data file stem; the stem is
// the provider id the proxy uses, so keep it visible next to the name.
const PROVIDER_LABEL: Record<string, string> = {
  anthropic: "Anthropic",
  bedrock: "AWS Bedrock",
  deepseek: "DeepSeek",
  google: "Google",
  groq: "Groq",
  mistral: "Mistral",
  openai: "OpenAI",
  together: "Together AI",
  xai: "xAI",
};

type Rate = {
  effective?: string;
  over?: number;
  input_per_million?: number;
  output_per_million?: number;
  cache_read_per_million?: number;
  cache_write_per_million?: number;
};

type Model = Rate & {
  name: string;
  audio_input_per_million?: number;
  audio_output_per_million?: number;
  reasoning_per_million?: number;
  scheduled?: Rate[];
  tiered?: Rate[];
};

type Provider = { provider: string; updated: string | null; models: Model[] };

const providers = pricing.providers as Provider[];

/** Rates span $0.0028 to $180 per million, so a fixed decimal count lies at one end. */
function usd(v: number | undefined): string {
  if (v === undefined) return "—";
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

function pair(r: Rate): string {
  return `${usd(r.input_per_million)} in / ${usd(r.output_per_million)} out`;
}

function notes(m: Model): string[] {
  const out: string[] = [];
  for (const t of m.tiered ?? []) {
    out.push(`over ${(t.over ?? 0) / 1000}k ctx: ${pair(t)}`);
  }
  for (const s of m.scheduled ?? []) {
    out.push(`from ${s.effective}: ${pair(s)}`);
  }
  if (m.audio_input_per_million !== undefined) {
    out.push(`audio: ${usd(m.audio_input_per_million)} in / ${usd(m.audio_output_per_million)} out`);
  }
  if (m.reasoning_per_million !== undefined) {
    out.push(`reasoning: ${usd(m.reasoning_per_million)}`);
  }
  return out;
}

const structuredData = {
  "@context": "https://schema.org",
  "@type": "Dataset",
  name: "LLM API pricing by model",
  description:
    "Per-million-token input, output and prompt-cache rates for large language models across nine API providers.",
  url: "https://burnlens.app/llm-pricing",
  creator: { "@type": "Organization", name: "BurnLens", url: "https://burnlens.app" },
  license: "https://opensource.org/licenses/MIT",
  variableMeasured: ["input price per million tokens", "output price per million tokens", "cache read price per million tokens", "cache write price per million tokens"],
};

export default function LlmPricing() {
  return (
    <div className="legal-page">
      <script type="application/ld+json">{JSON.stringify(structuredData)}</script>

      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>LLM API pricing</h1>
        <p className="legal-updated">
          {pricing.model_count} models · {providers.length} providers · all rates per million tokens, USD
        </p>

        <section>
          <p>
            This is not a hand-maintained marketing table. It is the exact pricing data the{" "}
            <Link href="/docs/proxy">BurnLens proxy</Link> bills every request from, generated from{" "}
            <code>{pricing.source}</code> in the open-source repo. When a rate changes there, this page
            changes with it.
          </p>
          <p>
            Cache columns matter more than they look. A coding agent re-sends its whole context every
            turn, so on Anthropic-style billing 90–99% of prompt tokens are cache reads at a tenth of
            the input rate — pricing a run off the input column alone overstates it by an order of
            magnitude.
          </p>
        </section>

        {providers.map((p) => (
          <section key={p.provider} id={p.provider}>
            <h2>{PROVIDER_LABEL[p.provider] ?? p.provider}</h2>
            <p className="legal-updated">
              <code>{p.provider}</code> · {p.models.length} models · rates verified {p.updated}
            </p>
            <div className="lp-compare-wrap">
              <table className="pricing-table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Input</th>
                    <th>Output</th>
                    <th>Cache read</th>
                    <th>Cache write</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {p.models.map((m) => (
                    <tr key={m.name}>
                      <td><code>{m.name}</code></td>
                      <td>{usd(m.input_per_million)}</td>
                      <td>{usd(m.output_per_million)}</td>
                      <td>{usd(m.cache_read_per_million)}</td>
                      <td>{usd(m.cache_write_per_million)}</td>
                      <td>{notes(m).join("; ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}

        <section>
          <h2>Reading the table</h2>
          <ul>
            <li><strong>Cache read / cache write</strong> — prompt-cache rates. An em dash means the provider does not bill caching separately.</li>
            <li><strong>OpenAI and Google fold cached tokens into the input count; Anthropic reports them separately.</strong> Adding cache reads to input tokens on an OpenAI response double-counts them.</li>
            <li><strong>over Nk ctx</strong> — a long-context tier. The higher rate applies to the whole request once the prompt crosses the threshold, not just the tokens above it.</li>
            <li><strong>from YYYY-MM-DD</strong> — a rate change the provider has already announced. The proxy switches on that date with no upgrade.</li>
            <li>Bedrock keys omit the geo prefix (<code>us.</code>, <code>eu.</code>, <code>apac.</code>, <code>global.</code>). These are global cross-region rates; regional inference runs roughly 10% higher.</li>
          </ul>
        </section>

        <section>
          <h2>Stop reading prices, start measuring them</h2>
          <p>
            A price list tells you the rate. It does not tell you what your agents actually spend, or
            which repo, PR, or developer spent it. BurnLens is a local proxy that does —{" "}
            <code>pip install burnlens</code>, one environment variable.
          </p>
          <p>
            <Link href="/docs">Read the docs</Link> · <Link href="/scan">Scan existing agent logs</Link> ·{" "}
            <Link href="/demo">See the dashboard</Link>
          </p>
        </section>
      </main>
    </div>
  );
}
