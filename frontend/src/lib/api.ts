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

/** FastAPI 422 entry: {loc: ["body", "name"], msg: "field required", type: "..."} */
interface ValidationEntry {
  loc?: unknown[];
  msg?: string;
}

/**
 * Turn any error body into one sentence a user can read.
 *
 * `err.message` from apiFetch is rendered directly in about ten places, so
 * every shape has to end up as a string. FastAPI's `detail` is a string for a
 * plain abort, an **object** for a structured one (`HTTPException(detail={…})`)
 * and an **array** for a 422 validation failure — the old code interpolated all
 * three, so the structured cases reached users as `[object Object]`. A body
 * that carries no readable message falls back to the status code rather than
 * leaking a serialised internal object.
 */
export function errorMessageFrom(body: unknown, status: number): string {
  const fallback = `Request failed (${status})`;
  if (!body || typeof body !== "object") return fallback;

  const detail = (body as { detail?: unknown }).detail;

  if (typeof detail === "string" && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    // 422: name the field, not just the rule — "name: field required" beats
    // "field required" when a form has more than one input.
    const parts = (detail as ValidationEntry[])
      .map((e) => {
        if (!e || typeof e.msg !== "string") return null;
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : undefined;
        return typeof field === "string" && field !== "body"
          ? `${field}: ${e.msg}`
          : e.msg;
      })
      .filter(Boolean);
    return parts.length ? parts.join("; ") : fallback;
  }

  // Structured detail, or a top-level shape. Only known message-bearing keys
  // are surfaced; anything else is backend internals and stays hidden.
  const source = (detail && typeof detail === "object" ? detail : body) as Record<string, unknown>;
  for (const key of ["message", "error", "msg"]) {
    const v = source[key];
    if (typeof v === "string" && v.trim()) return v;
  }
  return fallback;
}

/**
 * Issue the request and apply the shared failure handling, returning the raw
 * Response so the caller decides how to read the body.
 *
 * Split out of `apiFetch` because a CSV download needs identical auth, CSRF and
 * error semantics but must not have `.json()` called on it.
 */
async function apiRequest(endpoint: string, token: string, options: RequestInit = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
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
    // FastAPI wraps an HTTPException's `detail` payload one level down, so the
    // backend's {error, required_plan, limit, …} arrives as {detail: {…}} and
    // every `err.data.required_plan` read here was silently undefined. Unwrap
    // it once; a flat body (infra-level 402, or a plain-string detail) passes
    // through untouched.
    const detail = (body as { detail?: unknown }).detail;
    const data =
      detail && typeof detail === "object" && !Array.isArray(detail)
        ? (detail as PaymentRequiredBody)
        : (body as PaymentRequiredBody);
    throw new PaymentRequiredError(data);
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    throw new Error(errorMessageFrom(body, resp.status));
  }

  return resp;
}

export async function apiFetch(endpoint: string, token: string, options: RequestInit = {}) {
  const resp = await apiRequest(endpoint, token, options);
  return resp.json();
}

/** Pull `filename=…` off a Content-Disposition header, if the server sent one. */
function filenameFrom(disposition: string | null): string | null {
  if (!disposition) return null;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  return match ? decodeURIComponent(match[1].trim()) : null;
}

/**
 * Fetch an endpoint that returns a file and hand it to the browser as a
 * download. Failures throw the same errors `apiFetch` does, so a caller can
 * render `err.message` inline rather than leaving the user with a dead button.
 */
export async function apiDownload(
  endpoint: string,
  token: string,
  fallbackFilename: string,
  options: RequestInit = {}
): Promise<void> {
  const resp = await apiRequest(endpoint, token, options);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);

  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = filenameFrom(resp.headers.get("Content-Disposition")) ?? fallbackFilename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    // Revoking synchronously can cancel the download in Safari; one tick is
    // enough for the click to have been taken.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}
