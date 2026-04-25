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

// Phase 10 Plan 03: PaymentRequiredError now carries the Phase 9 D-14
// standardized 402 body so LockedPanel can render dynamic copy from
// `required_feature` / `required_plan`. Body is best-effort — if the upstream
// response has no JSON body (e.g. infra-level 402), `data` is an empty object
// and consumers fall back to defaults.
export interface PaymentRequiredBody {
  error?: string;              // "feature_not_in_plan"
  required_feature?: string;   // e.g., "teams_view", "customers_view"
  required_plan?: string;      // e.g., "teams"
  current_plan?: string;
  upgrade_url?: string;
  // Forward-compatible: backend may add more keys without breaking the client.
  [key: string]: unknown;
}

export class PaymentRequiredError extends Error {
  status: 402;
  data: PaymentRequiredBody;

  constructor(data: PaymentRequiredBody = {}, message: string = "Upgrade required") {
    super(message);
    this.name = "PaymentRequiredError";
    this.status = 402;
    this.data = data;
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
    // Phase 9 D-14: 402 carries a JSON body with required_feature / required_plan.
    // Best-effort parse — if the body is missing or malformed, throw with empty data
    // and let LockedPanel fall back to default copy.
    const body = await resp.json().catch(() => ({}));
    throw new PaymentRequiredError(body as PaymentRequiredBody);
  }

  if (!resp.ok) {
    const errorData = await resp.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(errorData.detail || `Request failed with status ${resp.status}`);
  }

  return resp.json();
}
