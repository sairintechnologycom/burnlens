# Proxy Interception & Provider Flow — BurnLens

## 1. Request Interception Path (The Hot Path)

When a developer sets `OPENAI_BASE_URL=http://localhost:8420/proxy/openai/v1`, requests follow this sequential pipeline:

```
[Application SDK] 
       │ (SDK Request)
       ▼
[FastAPI server.py: proxy_handler]
       │
       ▼
[interceptor.py: handle_request]
       ├─► 1. Resolve Provider: Matches path to provider adapter (e.g. OpenAI)
       ├─► 2. Extract Metadata: Read `X-BurnLens-Tag-*` headers for attribution tags
       ├─► 3. Hash System Prompt: Compute SHA-256 for loop/bloat analysis
       └─► 4. Forward: Call upstream provider using shared `httpx.AsyncClient`
```

---

## 2. Streaming (SSE) Passthrough Flow

Streaming calls (`"stream": true` in chat completions) require real-time chunk passthrough. BurnLens avoids buffering to guarantee sub-20ms latency:

```
[Upstream Provider] 
       │ (SSE Chunk 1)
       ▼
[streaming.py: StreamingResponse] ──► Flushed to client immediately
       │ (SSE Chunk 2)
       ▼
[streaming.py: StreamingResponse] ──► Flushed to client immediately
       ...
       │ (Final Chunk / Usage Block)
       ▼
[interceptor.py: log_cost]
       ├─► 1. Extract token usage from the final stream chunk (if present)
       ├─► 2. Calculate dollar cost via local pricing DB JSON
       └─► 3. Async Task: Store record in SQLite (does not block client response)
```

---

## 3. Provider Detection & Routing

BurnLens relies on a pattern-matching routing table mapping proxy request prefixes to upstream adapters:

| Incoming Path | Provider Code | Target Endpoint | Env Var Interceptor |
|---|---|---|---|
| `/proxy/openai/*` | `openai` | `https://api.openai.com` | `OPENAI_BASE_URL` |
| `/proxy/anthropic/*` | `anthropic` | `https://api.anthropic.com` | `ANTHROPIC_BASE_URL` |
| `/proxy/google/*` | `google` | `https://generativelanguage.googleapis.com` | `burnlens.patch` |

Custom signatures can be dynamically added to match self-hosted endpoints or local runners (e.g., Ollama or vLLM) using the `provider_signatures` catalog.
