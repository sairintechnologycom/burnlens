"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { motion, useInView } from "framer-motion";
import {
  BarChart3,
  Zap,
  ShieldCheck,
  Layers,
  Bell,
  ArrowRight,
  TrendingDown,
  Globe,
  Database,
} from "lucide-react";

const CHECKOUT = {
  personal: process.env.NEXT_PUBLIC_CHECKOUT_PERSONAL || "#pricing",
  team: process.env.NEXT_PUBLIC_CHECKOUT_TEAM || "#pricing",
};

function FadeIn({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  const ref = useRef(null);
  const isInView = useInView(ref, { once: true, margin: "-80px" });
  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 22 }}
      animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 22 }}
      transition={{ duration: 0.65, delay, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}

function StatCounter({ end, suffix = "", prefix = "" }: { end: number; suffix?: string; prefix?: string }) {
  const [val, setVal] = useState(0);
  const ref = useRef(null);
  const isInView = useInView(ref, { once: true });

  useEffect(() => {
    if (!isInView) return;
    let n = 0;
    const steps = 120;
    const step = end / steps;
    const t = setInterval(() => {
      n += step;
      if (n >= end) { n = end; clearInterval(t); }
      setVal(Math.round(n));
    }, 1000 / 60);
    return () => clearInterval(t);
  }, [isInView, end]);

  return <span ref={ref}>{prefix}{val.toLocaleString()}{suffix}</span>;
}

function FeatureCard({ icon: Icon, title, desc, delay }: { icon: any; title: string; desc: string; delay: number }) {
  return (
    <FadeIn delay={delay}>
      <div className="card">
        <div className="feat-icon">
          <Icon size={30} />
        </div>
        <h3 className="feat-title">{title}</h3>
        <p className="feat-desc">{desc}</p>
      </div>
    </FadeIn>
  );
}

function PricingCard({ 
  title, 
  price, 
  desc, 
  features, 
  btnText, 
  href, 
  featured = false, 
  delay = 0 
}: { 
  title: string; 
  price: string; 
  desc: string; 
  features: string[]; 
  btnText: string; 
  href: string; 
  featured?: boolean; 
  delay?: number;
}) {
  return (
    <FadeIn delay={delay}>
      <div className={`card ${featured ? "featured-card" : ""}`} style={{ 
        position: "relative", 
        display: "flex", 
        flexDirection: "column",
        borderColor: featured ? "var(--primary)" : "var(--card-border)",
        background: featured ? "rgba(116, 212, 165, 0.04)" : "var(--card-bg)"
      }}>
        {featured && (
          <div style={{ position: "absolute", top: -12, left: "50%", transform: "translateX(-50%)" }}>
            <span className="pill" style={{ background: "var(--primary)", color: "var(--background)" }}>MOST POPULAR</span>
          </div>
        )}
        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 18, fontWeight: 700, color: "#fff", marginBottom: 8 }}>{title}</h3>
          <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginBottom: 8 }}>
            <span style={{ fontSize: 32, fontWeight: 800, color: "#fff" }}>{price}</span>
            {price !== "Custom" && <span style={{ fontSize: 14, color: "var(--muted)" }}>one-time</span>}
          </div>
          <p style={{ fontSize: 14, color: "var(--muted)" }}>{desc}</p>
        </div>
        <div style={{ flex: 1, marginBottom: 32 }}>
          <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 12 }}>
            {features.map((f, i) => (
              <li key={i} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "#e0e0e0" }}>
                <ShieldCheck size={16} style={{ color: "var(--primary)", flexShrink: 0 }} />
                {f}
              </li>
            ))}
          </ul>
        </div>
        <Link href={href} className={`btn ${featured ? "btn-primary" : ""} w-full h-10`} style={{ height: 48 }}>
          {btnText}
        </Link>
      </div>
    </FadeIn>
  );
}

export default function LandingPage() {
  return (
    <div style={{ minHeight: "100vh" }}>

      {/* ═══ NAV ═══ */}
      <nav className="glass nav">
        <div className="nav-logo">
          <div className="nav-logo-icon">⊡</div>
          <span className="nav-brand">BurnLens</span>
        </div>

        <div className="nav-links">
          <Link href="#features" className="nav-link">Features</Link>
          <Link href="#pricing" className="nav-link">Pricing</Link>
          <Link href="https://github.com/bhushan/burnlens" target="_blank" className="nav-link">GitHub</Link>
        </div>

        <div className="nav-actions">
          <Link href="/dashboard" className="btn">Dashboard</Link>
          <Link href="#pricing" className="btn btn-primary">Get Started</Link>
        </div>
      </nav>

      {/* ═══ HERO ═══ */}
      <section className="hero">
        <div className="hero-glow" />
        <div className="hero-content">
          <FadeIn>
            <span className="pill">AI FinOps for builders</span>
          </FadeIn>

          <FadeIn delay={0.12}>
            <h1 className="hero-title">
              Stop overpaying for<br />
              <span className="gradient-text">AI API calls</span>
            </h1>
          </FadeIn>

          <FadeIn delay={0.22}>
            <p className="hero-subtitle">
              Connect your Anthropic, OpenAI &amp; Google AI accounts.
              See exactly where every dollar goes. Cut costs by 40–60%
              with actionable, automated recommendations.
            </p>
          </FadeIn>

          <FadeIn delay={0.32}>
            <div className="hero-cta">
              <Link href="#pricing" className="btn btn-primary btn-lg">
                Get BurnLens — $149
              </Link>
              <Link href="/setup" className="btn btn-lg" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                Launch Dashboard <ArrowRight size={17} />
              </Link>
            </div>
          </FadeIn>

          <FadeIn delay={0.42}>
            <p className="hero-note">
              One-time purchase · Self-hosted Docker · Full Privacy
            </p>
          </FadeIn>
        </div>
      </section>

      {/* ═══ STATS ═══ */}
      <section className="stats-section">
        <div className="stats-grid">
          {[
            { n: 40, suffix: "–60%", label: "Avg. cost reduction" },
            { n: 3,  suffix: " min", label: "Setup time" },
            { n: 3,  suffix: "",     label: "Providers supported" },
            { n: 5,  suffix: "",     label: "Optimization rules" },
          ].map((s, i) => (
            <div key={i} className="stat-item">
              <div className="stat-num">
                <StatCounter end={s.n} suffix={s.suffix} />
              </div>
              <div className="stat-label">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ═══ FEATURES ═══ */}
      <section id="features" className="features-section">
        <FadeIn>
          <div className="section-header">
            <h2 className="section-title">Built for builders who ship</h2>
            <p className="section-subtitle">
              The tools you need to build cost-efficient AI products from day one.
            </p>
          </div>
        </FadeIn>

        <div className="features-grid">
          <FeatureCard delay={0.0} icon={Globe}        title="Multi-Provider"  desc="Anthropic, OpenAI, Google AI in one dashboard. One view for all your LLM spend." />
          <FeatureCard delay={0.1} icon={Layers}       title="Cost by Feature" desc="Tag API calls to product features. Know the true cost of your summarize vs. chat vs. search." />
          <FeatureCard delay={0.2} icon={TrendingDown} title="Smart Optimizer" desc="5 rule engines: model downgrade, prompt caching, batch API, and provider arbitrage." />
          <FeatureCard delay={0.3} icon={Database}     title="Self-Hosted"     desc="Runs as a single Docker container. Your API keys and data never leave your infrastructure." />
          <FeatureCard delay={0.4} icon={Bell}         title="Budget Alerts"   desc="Set daily or monthly spend thresholds. Get Slack or webhook notifications before bills surprise you." />
          <FeatureCard delay={0.5} icon={Zap}          title="API-First"       desc="Full REST API. Integrate cost checks into your CI/CD pipeline or block deploys based on budget." />
        </div>
      </section>

      {/* ═══ PRICING ═══ */}
      <section id="pricing" className="features-section" style={{ borderTop: "1px solid var(--card-border)", paddingTop: 96 }}>
        <FadeIn>
          <div className="section-header">
            <h2 className="section-title">Investment with massive ROI</h2>
            <p className="section-subtitle">
              BurnLens pays for itself in weeks by identifying waste you didn't know existed.
            </p>
          </div>
        </FadeIn>

        <div className="grid-3" style={{ maxWidth: 1000, marginInline: "auto" }}>
          <PricingCard 
            delay={0.1}
            title="Personal"
            price="$149"
            desc="Perfect for solo builders and side projects."
            features={[
              "Self-hosted Docker",
              "1 Administrator seat",
              "30-day usage history",
              "Core optimization engine",
              "Email notifications",
              "Community support"
            ]}
            btnText="Buy Personal"
            href={CHECKOUT.personal}
          />
          <PricingCard 
            delay={0}
            featured={true}
            title="Team"
            price="$499"
            desc="For startups scaling their AI infrastructure."
            features={[
              "Everything in Personal",
              "5 Administrator seats",
              "Unlimited usage history",
              "Full optimization engine",
              "Slack / Webhook alerts",
              "Priority support"
            ]}
            btnText="Buy Team"
            href={CHECKOUT.team}
          />
          <PricingCard 
            delay={0.2}
            title="Enterprise"
            price="Custom"
            desc="For high-volume AI organizations."
            features={[
              "Everything in Team",
              "Unlimited seats",
              "SSO & Audit logs",
              "Multi-org management",
              "Vulnerability scanning",
              "Dedicated account manager"
            ]}
            btnText="Contact Sales"
            href="mailto:hello@burnlens.dev"
          />
        </div>
      </section>

      {/* ═══ CTA ═══ */}
      <section className="cta-section">
        <FadeIn>
          <div className="cta-inner">
            <h2 className="cta-title">Ready to cut your AI bill in half?</h2>
            <p className="cta-sub">
              Join 200+ companies using BurnLens to ship AI features without the sticker shock.
            </p>
            <div className="cta-btns">
              <Link href="#pricing" className="btn btn-primary btn-lg">Get Started Now</Link>
              <Link href="https://github.com/bhushan/burnlens" className="btn btn-lg">View Documentation</Link>
            </div>
          </div>
        </FadeIn>
      </section>

      {/* ═══ FOOTER ═══ */}
      <footer className="footer">
        <p className="footer-text">
          BurnLens &copy; 2026 · AI FinOps · Self-Hosted &amp; Secure
        </p>
      </footer>
    </div>
  );
}
