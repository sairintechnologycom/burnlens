import { ImageResponse } from "next/og";

export const dynamic = "force-static";

export const alt = "BurnLens — See exactly what your AI API calls cost";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "80px",
          background:
            "radial-gradient(ellipse at top left, rgba(0,229,200,0.12) 0%, transparent 55%), radial-gradient(ellipse at bottom right, rgba(255,107,74,0.10) 0%, transparent 55%), #080c10",
          color: "#e6edf3",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "16px",
            fontSize: 32,
            letterSpacing: "0.2em",
            fontWeight: 700,
            color: "#00e5c8",
          }}
        >
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: 10,
              background: "#00e5c8",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#080c10",
              fontSize: 28,
              fontWeight: 800,
            }}
          >
            B
          </div>
          BURNLENS
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              fontSize: 76,
              fontWeight: 800,
              lineHeight: 1.05,
              letterSpacing: "-0.02em",
              color: "#ffffff",
            }}
          >
            <div style={{ display: "flex" }}>See exactly what your</div>
            <div style={{ display: "flex" }}>AI API calls cost.</div>
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              fontSize: 30,
              color: "#8b949e",
              lineHeight: 1.35,
              maxWidth: 900,
            }}
          >
            <div style={{ display: "flex" }}>
              One command. Zero code changes. Every dollar tracked.
            </div>
            <div style={{ display: "flex" }}>
              Open-source LLM FinOps for Anthropic, OpenAI &amp; Google AI.
            </div>
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "20px",
            fontSize: 26,
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            color: "#00e5c8",
          }}
        >
          <div style={{ color: "#8b949e" }}>$</div>
          <div>pip install burnlens &amp;&amp; burnlens start</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
