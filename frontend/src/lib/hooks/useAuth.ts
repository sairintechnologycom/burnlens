"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export interface AuthSession {
  // Post C-3: the real JWT now lives in the `burnlens_session` HttpOnly cookie
  // and is never readable from JS. The `token` field is a sentinel
  // ("cookie" for remote sessions, "local" for the local proxy) that lets
  // `apiFetch` decide whether to send `credentials: "include"`.
  token: string;
  workspaceId: string;
  workspaceName: string;
  plan: string;
  apiKey: string;
  isLocal: boolean;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8420";

function isLocalBackend(): boolean {
  try {
    const url = new URL(API_BASE);
    const host = url.hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0";
  } catch {
    return true;
  }
}

const LOCAL_SESSION: AuthSession = {
  token: "local",
  workspaceId: "local",
  workspaceName: "Local",
  plan: "free",
  apiKey: "local",
  isLocal: true,
};

export function useAuth() {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isLocalBackend()) {
      setSession(LOCAL_SESSION);
      setLoading(false);
      return;
    }

    // Workspace metadata stays in localStorage (non-sensitive). Its presence
    // is the client-side hint that a session cookie was issued at login.
    const workspaceId = localStorage.getItem("burnlens_workspace_id");
    const workspaceName = localStorage.getItem("burnlens_workspace_name");
    const plan = localStorage.getItem("burnlens_plan");
    const apiKey = localStorage.getItem("burnlens_api_key");

    // One-time cleanup: purge any legacy JWT still sitting in localStorage
    // from pre-C-3 sessions so an XSS landing later cannot read it.
    if (typeof window !== "undefined") {
      localStorage.removeItem("burnlens_token");
    }

    if (!workspaceId) {
      router.push("/setup");
      return;
    }

    setSession({
      token: "cookie",
      workspaceId,
      workspaceName: workspaceName || "My Organization",
      plan: plan || "free",
      apiKey: apiKey || "",
      isLocal: false,
    });
    setLoading(false);
  }, [router]);

  const logout = useCallback(() => {
    // Fire-and-forget; we clear client state even if the network call fails.
    if (!isLocalBackend()) {
      fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        credentials: "include",
      }).catch(() => {});
    }
    localStorage.removeItem("burnlens_token");
    localStorage.removeItem("burnlens_workspace_id");
    localStorage.removeItem("burnlens_workspace_name");
    localStorage.removeItem("burnlens_plan");
    localStorage.removeItem("burnlens_api_key");
    setSession(null);
    if (isLocalBackend()) {
      router.push("/");
    } else {
      router.push("/setup");
    }
  }, [router]);

  return { session, loading, logout };
}
