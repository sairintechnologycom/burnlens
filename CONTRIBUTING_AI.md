# Contributing Rules for AI Coding Assistants (Codex/Gemini/Claude)

Welcome, AI agent! This repository is a developer proxy tool. Modifying it requires strict adherence to these rules to avoid regressions.

## Non-Negotiable Core Rules

1. **Do Not Break Local-First Mode**:
   - The CLI `burnlens start` command, the local FastAPI proxy server, local SQLite database, and the HTML/JS dashboard MUST continue to work without an internet connection or a SaaS login.

2. **Fail Open Policy**:
   - If BurnLens fails to compute a cost, fails to write to SQLite, or encounters a configuration issue, the proxy MUST log a warning and continue to forward the request upstream. Never disrupt the user's application traffic.

3. **Strict Streaming Passthrough**:
   - Never buffer streaming response bodies. Server-Sent Events (SSE) must be written and flushed to the client chunk-by-chunk immediately as they arrive from the upstream provider.

4. **Zero Request/Response Modifications**:
   - The proxy is a transparent proxy. Do not alter the request headers (except BurnLens-specific headers), query parameters, or body contents sent upstream. Do not modify response bodies sent back to the caller.

5. **Privacy Guarantee**:
   - Cloud synchronization batches sent to `burnlens.app` MUST NEVER upload prompt or response texts. Only send one-way hashes (SHA-256) of system prompts and numeric token/cost metadata.

6. **Feature Flags**:
   - New capabilities (e.g., OTel exporting, write-ahead logging, semantic caching, routing) must be developed behind feature flags using `burnlens.feature_flags.is_enabled("flag_name")`. Keep them disabled by default.

7. **Development Guidelines**:
   - Use `async`/`await` for all proxy hot-path I/O. Use `aiosqlite` for SQLite operations, `asyncpg` for PostgreSQL cloud operations, and `httpx.AsyncClient` for forwarding.
   - Maintain full type hinting on all public methods and modules.
