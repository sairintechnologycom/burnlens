"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export interface AuthSession {
  orgId: string;
  apiKey: string;
  orgName: string;
  isLocal: boolean;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8420";

function isLocalBackend(): boolean {
  try {
    const url = new URL(API_BASE);
    const host = url.hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0";
  } catch {
    return true; // default to local if URL is malformed
  }
}

const LOCAL_SESSION: AuthSession = {
  orgId: "local",
  apiKey: "local",
  orgName: "Local",
  isLocal: true,
};

export function useAuth() {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Local mode: skip auth entirely
    if (isLocalBackend()) {
      setSession(LOCAL_SESSION);
      setLoading(false);
      return;
    }

    // Cloud mode: check localStorage for API key
    const apiKey = localStorage.getItem("burnlens_api_key");
    const orgId = localStorage.getItem("burnlens_org_id");
    const orgName = localStorage.getItem("burnlens_org_name");

    if (!apiKey) {
      router.push("/setup");
      return;
    }

    setSession({
      orgId: orgId || "",
      apiKey,
      orgName: orgName || "My Organization",
      isLocal: false,
    });
    setLoading(false);
  }, [router]);

  const logout = useCallback(() => {
    localStorage.removeItem("burnlens_api_key");
    localStorage.removeItem("burnlens_org_id");
    localStorage.removeItem("burnlens_org_name");
    setSession(null);
    if (isLocalBackend()) {
      // Local mode: just go to landing page
      router.push("/");
    } else {
      router.push("/setup");
    }
  }, [router]);

  return { session, loading, logout };
}
