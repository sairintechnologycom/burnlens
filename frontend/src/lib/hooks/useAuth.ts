"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export interface AuthSession {
  orgId: string;
  apiKey: string;
  orgName: string;
}

export function useAuth() {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
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
      orgName: orgName || "My Organization"
    });
    setLoading(false);
  }, [router]);

  const logout = () => {
    localStorage.removeItem("burnlens_api_key");
    localStorage.removeItem("burnlens_org_id");
    localStorage.removeItem("burnlens_org_name");
    setSession(null);
    router.push("/setup");
  };

  return { session, loading, logout };
}
