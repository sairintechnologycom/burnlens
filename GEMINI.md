# BurnLens Security Standards (GEMINI.md)

## 1. Telemetry Ingestion
- **Integrity**: All telemetry ingestion requests MUST be signed using HMAC-SHA256 of the records list, with the workspace API key as the secret.
- **Verification**: The cloud ingest API MUST verify the signature before processing records.

## 2. SSRF Prevention
- **URL Validation**: Any user-supplied endpoint (e.g., for OTEL forwarding) MUST be validated.
- **Rules**: Only HTTPS is allowed. Internal/Private IP ranges and cloud metadata services MUST be blocked.

## 3. CSRF Protection
- **Header-Based**: All state-changing API requests (POST, PUT, DELETE, PATCH) to the cloud dashboard MUST include the `X-Requested-With: XMLHttpRequest` header.
- **Middleware**: The backend MUST enforce this requirement.

## 4. Tag Security
- **Allowlisting**: Only canonical tags defined in `burnlens.proxy.interceptor._ALLOWED_TAGS` are extracted from headers/env. This prevents tag injection spoofing.
- **Sanitization**: Tag values are truncated to 100 characters and stripped of whitespace.

## 5. Cache Integrity
- **Verification**: All semantic cache entries MUST store a SHA-256 hash of the response body.
- **Signatures**: If a `SECRET_KEY` is configured, entries MUST also include an HMAC-SHA256 signature.
- **Validation**: Hashes and signatures MUST be verified upon cache lookup.

## 6. Infrastructure
- **WAF**: Production load balancers MUST be protected by AWS WAF with Amazon Managed Rules.
- **Secrets**: All sensitive credentials (DB URLs, JWT secrets, Proxy secrets) MUST be managed via AWS Secrets Manager.
