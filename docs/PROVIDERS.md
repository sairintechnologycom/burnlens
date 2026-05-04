# Adding a New Provider

Adding a provider to BurnLens takes one new file in `burnlens/providers/` and one
new pricing JSON in `burnlens/cost/pricing_data/`.  No core changes required.

---

## Quick-start: Groq in ~30 lines

```python
# burnlens/providers/groq.py
"""Groq provider plugin — OpenAI-compatible API."""
from __future__ import annotations

import json
from typing import Optional

from burnlens.cost.calculator import TokenUsage, extract_usage_openai
from burnlens.providers.base import Provider, ProviderConfig


class GroqProvider(Provider):
    config = ProviderConfig(
        name="groq",
        proxy_path="/proxy/groq",
        upstream_url="https://api.groq.com/openai",
        auth_header="Authorization",
        streaming_format="sse-openai",   # same body shape as OpenAI
        pricing_key="groq",              # → burnlens/cost/pricing_data/groq.json
        env_var="GROQ_BASE_URL",
    )

    def resolve_upstream_url(self, request_path: str, headers: dict[str, str]) -> str:
        return self.config.upstream_url + request_path

    def extract_model(self, request_body: dict, request_path: str) -> Optional[str]:
        return request_body.get("model")

    def extract_usage(self, response_body: dict) -> TokenUsage:
        return extract_usage_openai(response_body)   # same schema as OpenAI

    def extract_usage_from_stream_chunk(
        self, chunk: bytes, accumulator: dict
    ) -> Optional[TokenUsage]:
        chunk_str = chunk.decode("utf-8", errors="ignore")
        for line in chunk_str.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
                u = data.get("usage")
                if u:
                    accumulator["input_tokens"] = u.get("prompt_tokens", 0)
                    accumulator["output_tokens"] = u.get("completion_tokens", 0)
            except Exception:
                pass
        return None

    def should_buffer_chunk(self, chunk: bytes) -> bool:
        return b'"usage"' in chunk


groq_provider = GroqProvider()
```

Then register it in `burnlens/providers/__init__.py`:

```python
from burnlens.providers.groq import groq_provider
register(groq_provider)
```

And add `burnlens/cost/pricing_data/groq.json`:

```json
{
  "provider": "groq",
  "updated": "2025-01-01",
  "models": {
    "llama-3.3-70b-versatile": {
      "input_per_million": 0.59,
      "output_per_million": 0.79
    },
    "llama-3.1-8b-instant": {
      "input_per_million": 0.05,
      "output_per_million": 0.08
    }
  }
}
```

That's it.  BurnLens will proxy `GROQ_BASE_URL=http://127.0.0.1:8420/proxy/groq`
requests, log every call with real cost, and show it in the dashboard.

---

## The six methods to implement

| Method | Required | Purpose |
|--------|----------|---------|
| `resolve_upstream_url(request_path, headers)` | Yes | Build full upstream URL from stripped path |
| `extract_model(request_body, request_path)` | Yes | Return model name or `None` |
| `extract_usage(response_body)` | Yes | Non-streaming token extraction |
| `extract_usage_from_stream_chunk(chunk, accumulator)` | Yes | Accumulate streaming usage into dict |
| `should_buffer_chunk(chunk)` | Yes | Filter chunks containing usage data |
| `normalize_model_name(raw_model)` | No | Map API model name to pricing key |

### accumulator keys

`extract_usage_from_stream_chunk` mutates the `accumulator` dict using these
string keys: `input_tokens`, `output_tokens`, `reasoning_tokens`,
`cache_read_tokens`, `cache_write_tokens`.  After all chunks are processed,
`streaming.extract_usage_from_stream` builds a `TokenUsage` from the accumulator.

---

## Pricing JSON format

```json
{
  "provider": "my-provider",
  "updated": "YYYY-MM-DD",
  "models": {
    "model-name": {
      "input_per_million":        1.00,
      "output_per_million":       3.00,
      "reasoning_per_million":    3.00,
      "cache_read_per_million":   0.10,
      "cache_write_per_million":  3.75
    }
  }
}
```

All rates are in USD per 1 million tokens.  Omit keys that don't apply.
Prefix matching is used: `gpt-4o-2024-11-20` will fall back to a `gpt-4o` entry.

---

## Future base classes (planned for M-3)

For providers that share the OpenAI wire format (Groq, Together, Mistral),
an `OpenAICompatibleProvider` base will be added that implements all six methods
using the standard OpenAI SSE schema.  Your provider will reduce to just the
`ProviderConfig` declaration.

```python
# Future — not yet available
from burnlens.providers.openai_compat import OpenAICompatibleProvider

class GroqProvider(OpenAICompatibleProvider):
    config = ProviderConfig(name="groq", upstream_url="https://api.groq.com/openai", ...)
```

---

## Planned providers (M-2 / M-3)

| Provider | Pricing key | Notes |
|----------|-------------|-------|
| Azure OpenAI | `azure-openai` | Deployment name in URL, different prices |
| AWS Bedrock | `bedrock` | AWS EventStream format, model in path |
| Groq | `groq` | OpenAI-compatible |
| Together AI | `together` | OpenAI-compatible |
| Mistral | `mistral` | OpenAI-compatible |
| Google Vertex AI | `google-vertex` | Different prices than google.json |
