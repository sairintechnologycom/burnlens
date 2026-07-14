"""Azure OpenAI provider plugin.

Azure serves the OpenAI models over the same chat-completions wire format
(request body, usage block, SSE streaming), so all parsing is inherited from
OpenAIProvider.  Only two things differ:

* **Endpoint** — per-resource (``https://<resource>.openai.azure.com``), so it
  can't be hardcoded like api.openai.com.  The proxy reads the real resource
  URL from ``BURNLENS_AZURE_ENDPOINT`` at request time.  (The client-side
  ``AZURE_OPENAI_ENDPOINT`` that the AzureOpenAI SDK reads is repointed at
  BurnLens by the CLI wrapper — a *different* var, so the two never collide.)
* **Auth** — Azure uses the ``api-key`` header instead of ``Authorization``.
  It's forwarded to upstream untouched, so this is only metadata.

The model in a request is the Azure *deployment* name (in both the URL path
and the body).  Pricing reuses ``openai.json``: when a deployment is named
after its model (the common convention, e.g. ``gpt-4o``) costs resolve; a
deployment named arbitrarily prices at $0 until a name→model map is added.
"""
from __future__ import annotations

import os
from typing import Optional

from burnlens.providers.base import ProviderConfig
from burnlens.providers.openai import OpenAIProvider

UPSTREAM_ENV = "BURNLENS_AZURE_ENDPOINT"


class AzureOpenAIProvider(OpenAIProvider):
    config = ProviderConfig(
        name="azure",
        proxy_path="/proxy/azure",
        upstream_url="",  # per-resource; resolved from BURNLENS_AZURE_ENDPOINT
        auth_header="api-key",
        streaming_format="sse-openai",
        pricing_key="openai",  # Azure serves OpenAI models at OpenAI prices
        env_var="AZURE_OPENAI_ENDPOINT",  # SDK var the CLI wrapper repoints
    )

    @property
    def upstream_base(self) -> str:
        endpoint = os.environ.get(UPSTREAM_ENV, "").rstrip("/")
        if not endpoint:
            raise RuntimeError(
                f"Azure provider requires {UPSTREAM_ENV} to be set to your "
                "resource endpoint, e.g. https://<resource>.openai.azure.com"
            )
        return endpoint

    def resolve_upstream_url(self, request_path: str, headers: dict[str, str]) -> str:
        return self.upstream_base + request_path

    def extract_model(self, request_body: dict, request_path: str) -> Optional[str]:
        # AzureOpenAI SDK sends the deployment name in the body as "model".
        # Fall back to the /deployments/{name}/ segment for clients that don't.
        model = request_body.get("model")
        if model:
            return model
        parts = request_path.split("?", 1)[0].split("/")
        for i, part in enumerate(parts):
            if part == "deployments" and i + 1 < len(parts):
                return parts[i + 1] or None
        return None


azure_provider = AzureOpenAIProvider()
