"use client";

import { ArrowUpRight, Lock } from "lucide-react";
import { motion } from "framer-motion";

export default function UpgradePrompt({ feature }: { feature: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="card"
      style={{
        padding: 48,
        textAlign: "center",
        background: "rgba(212,165,116,0.03)",
        borderColor: "rgba(212,165,116,0.15)",
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: 16,
          background: "rgba(212,165,116,0.1)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          margin: "0 auto 20px",
          color: "var(--accent)",
        }}
      >
        <Lock size={24} />
      </div>
      <h3
        className="text-white font-bold text-lg"
        style={{ marginBottom: 8 }}
      >
        {feature} requires Team plan
      </h3>
      <p
        className="text-muted text-sm"
        style={{ marginBottom: 24, maxWidth: 360, margin: "0 auto 24px" }}
      >
        Upgrade to the Team plan to unlock {feature.toLowerCase()}, team-level attribution, and advanced analytics.
      </p>
      <a
        href="/settings"
        className="btn btn-primary"
        style={{
          padding: "12px 28px",
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        Upgrade Plan
        <ArrowUpRight size={16} />
      </a>
    </motion.div>
  );
}
