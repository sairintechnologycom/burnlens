"use client";

import { useMemo, useState } from "react";
import { estimate, providers, type Model } from "./estimate";

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

// A coding-agent turn: large re-sent context, mostly cache-read, short reply.
// Defaults matter more than the inputs — most visitors never touch a field.
const DEFAULTS = { promptTokens: 60000, outputTokens: 1500, cachedPct: 90, requests: 400 };

function money(v: number): string {
  if (v === 0) return "$0.00";
  if (v < 0.01) return `$${v.toFixed(5)}`;
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function find(id: string): { provider: string; model: Model } {
  const [provider, ...rest] = id.split("/");
  const name = rest.join("/");
  const p = providers.find((x) => x.provider === provider)!;
  return { provider, model: p.models.find((m) => m.name === name)! };
}

function defaultModel(): string {
  const anthropic = providers.find((p) => p.provider === "anthropic");
  const opus = anthropic?.models.find((m) => m.name.startsWith("claude-opus-5"));
  if (anthropic && opus) return `anthropic/${opus.name}`;
  return `${providers[0].provider}/${providers[0].models[0].name}`;
}

export default function Calculator() {
  const [id, setId] = useState(defaultModel);
  const [v, setV] = useState(DEFAULTS);

  const { provider, model } = find(id);
  // Scheduled rates switch on a date, so price against the reader's today.
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const r = estimate(provider, model, v, today);

  const num = (key: keyof typeof DEFAULTS, label: string, max: number, hint?: string) => (
    <label className="lp-calc-field">
      <span className="form-label">{label}</span>
      <input
        className="form-input"
        type="number"
        min={0}
        max={max}
        value={v[key]}
        onChange={(e) => setV({ ...v, [key]: Math.min(max, Math.max(0, Number(e.target.value) || 0)) })}
      />
      {hint ? <span className="lp-calc-hint">{hint}</span> : null}
    </label>
  );

  return (
    <section id="calculator">
      <h2>What will it actually cost?</h2>
      <p>
        Most token calculators price the whole prompt at the input rate. Coding agents re-send their
        context every turn, so almost all of it is a cache read at a fraction of that rate — and the
        naive answer comes out several times too high. This one bills the way the provider does.
      </p>

      <div className="lp-calc">
        <label className="lp-calc-field lp-calc-model">
          <span className="form-label">Model</span>
          <select className="form-input" value={id} onChange={(e) => setId(e.target.value)}>
            {providers.map((p) => (
              <optgroup key={p.provider} label={PROVIDER_LABEL[p.provider] ?? p.provider}>
                {p.models.map((m) => (
                  <option key={m.name} value={`${p.provider}/${m.name}`}>{m.name}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        {num("promptTokens", "Prompt tokens", 10_000_000, "per request, including the cached part")}
        {num("cachedPct", "Cached share %", 100, "90–99% for a coding agent mid-session")}
        {num("outputTokens", "Output tokens", 1_000_000)}
        {num("requests", "Requests", 10_000_000, "per month, per developer")}
      </div>

      <div className="lp-calc-out">
        <div className="lp-calc-total">
          <span className="form-label">Total</span>
          <strong>{money(r.total)}</strong>
        </div>
        <div className="lp-calc-total">
          <span className="form-label">Per request</span>
          <strong>{money(r.perRequest)}</strong>
        </div>
        <div className="lp-calc-total">
          <span className="form-label">Priced the naive way</span>
          <strong className="lp-calc-naive">{money(r.naivePerRequest * v.requests)}</strong>
        </div>
      </div>

      <ul className="lp-calc-notes">
        <li>
          {r.cacheAware
            ? `${r.cacheReadTokens.toLocaleString()} of the ${v.promptTokens.toLocaleString()} prompt tokens bill at the cache-read rate.`
            : `${PROVIDER_LABEL[provider] ?? provider} does not bill cached tokens separately for this model, so the cached share costs full input price.`}
        </li>
        <li>
          {provider === "anthropic" || provider === "bedrock"
            ? "Anthropic-style billing reports cache reads separately from the prompt count."
            : "This provider folds cached tokens into its reported prompt count — adding the two double-counts them."}
        </li>
        {r.tierApplied ? <li>Long-context tier applied: the whole request bills at the higher rate.</li> : null}
        <li>
          Steady state only — the turn that first populates the cache pays a one-off write premium, and
          reasoning, audio and per-image fees are not modelled.
        </li>
      </ul>
    </section>
  );
}
