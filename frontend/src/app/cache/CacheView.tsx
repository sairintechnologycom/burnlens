import type { CacheOverview } from "@/lib/contracts";

// Presentational half of the cache page, split out (waste/FindingsList
// pattern) so the populated state is testable without hooks or fetches.
export function cacheRatePct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

export function CacheView({ data, days }: { data: CacheOverview; days: number }) {
  return (
    <div>
      <div className="stat-strip">
        {/* Prompt = uncached input + cache reads + writes. Never show the
            uncached share alone in a cost context. */}
        <div className="stat-cell">
          <div className="stat-label">Prompt tokens</div>
          <div className="stat-value">{data.prompt_tokens.toLocaleString()}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Served from cache</div>
          <div className="stat-value cyan" data-testid="cache-rate">
            {cacheRatePct(data.cache_read_rate)}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Cache reads</div>
          <div className="stat-value">{data.cache_read_tokens.toLocaleString()}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Cache writes</div>
          <div className="stat-value">{data.cache_write_tokens.toLocaleString()}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Proxy cache saved</div>
          <div className="stat-value" style={{ color: "var(--green)" }}>
            ${data.proxy_cache_saved_usd.toFixed(2)}
            <span style={{ fontSize: 11, color: "var(--muted)", marginLeft: 6 }}>
              {data.proxy_cache_hits.toLocaleString()} hits
            </span>
          </div>
        </div>
      </div>

      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Cache share by model</span>
          <span className="section-header-action">{days}d</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Model</th>
              <th>Requests</th>
              <th>Prompt tokens</th>
              <th>Cache reads</th>
              <th>Cache rate</th>
            </tr>
          </thead>
          <tbody>
            {data.by_model.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>
                  No requests in this window yet. Cache data appears once the
                  proxy or a scan has synced traffic.
                </td>
              </tr>
            ) : (
              data.by_model.map((m) => (
                <tr key={m.model} data-testid="cache-model-row">
                  <td style={{ fontWeight: 500 }}>{m.model}</td>
                  <td>{m.request_count.toLocaleString()}</td>
                  <td>{m.prompt_tokens.toLocaleString()}</td>
                  <td>{m.cache_read_tokens.toLocaleString()}</td>
                  <td style={{ color: m.cache_read_rate >= 0.5 ? "var(--green)" : undefined }}>
                    {cacheRatePct(m.cache_read_rate)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        <div
          style={{
            padding: "10px 16px 14px",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--muted)",
          }}
        >
          Cache rate = provider cache reads over the whole prompt. Rows synced
          before cache tracking existed count as 0% and dilute the rate.
        </div>
      </div>
    </div>
  );
}
