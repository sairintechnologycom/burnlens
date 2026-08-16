"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";
import type { CacheOverview } from "@/lib/contracts";
import { CacheView } from "./CacheView";

function CacheContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [data, setData] = useState<CacheOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    apiFetch(`/api/v1/usage/cache?days=${days}`, session.token)
      .then((res) => setData(res as CacheOverview))
      .catch((err: any) => {
        if (err instanceof AuthError) logout();
        else setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [session, days, logout]);

  useEffect(() => {
    document.title = "Caching | BurnLens";
  }, []);

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <div className="skeleton" style={{ height: 64, marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 240 }} />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ padding: 24 }}>
        <span className="error-inline" onClick={() => window.location.reload()}>
          Couldn’t reach server — retry &#x2197;
        </span>
      </div>
    );
  }

  return <CacheView data={data} days={days} />;
}

export default function CachePage() {
  return (
    <Shell>
      <CacheContent />
    </Shell>
  );
}
