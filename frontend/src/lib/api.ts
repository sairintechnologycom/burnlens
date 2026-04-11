"use client";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class AuthError extends Error {
  constructor(message: string = "Invalid API key") {
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

export async function apiFetch(endpoint: string, apiKey: string, options: RequestInit = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const headers = {
    ...options.headers,
    "X-API-Key": apiKey,
    "Content-Type": "application/json",
  };

  const resp = await fetch(url, { ...options, headers });
  
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

