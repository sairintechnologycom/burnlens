"use client";

function resolveBaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_URL;
  if (fromEnv) return fromEnv;
  if (typeof window !== "undefined" && window.location.hostname !== "localhost") {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not set. Public builds must point at a reachable API origin (e.g. https://api.burnlens.app)."
    );
  }
  return "http://localhost:8420";
}

const BASE_URL = resolveBaseUrl();

export { BASE_URL };

export class AuthError extends Error {
  constructor(message: string = "Session expired") {
    super(message);
    this.name = "AuthError";
  }
}

export class PaymentRequiredError extends Error {
  constructor(message: string = "Upgrade required") {
    super(message);
    this.name = "PaymentRequiredError";
  }
}

export async function apiFetch(endpoint: string, token: string, options: RequestInit = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
    "Content-Type": "application/json",
  };

  // C-3: auth is transported via the `burnlens_session` HttpOnly cookie set at
  // login/signup. The `token` argument is retained for call-site compatibility
  // and to discriminate the local-proxy case; its value is no longer sent.
  const isRemoteSession = token && token !== "local";

  const resp = await fetch(url, {
    ...options,
    headers,
    credentials: isRemoteSession ? "include" : (options.credentials ?? "same-origin"),
  });

  if (resp.status === 401) {
    throw new AuthError();
  }

  if (resp.status === 402) {
    throw new PaymentRequiredError();
  }

  if (!resp.ok) {
    const errorData = await resp.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(errorData.detail || `Request failed with status ${resp.status}`);
  }

  return resp.json();
}
