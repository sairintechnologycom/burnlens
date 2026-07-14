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
and the body).  Pricing reuses ``openai.json``: a deployment named after its
model (the common convention, e.g. ``gpt-4o``) resolves directly; Azure's
dotless ``gpt-35-turbo`` spellings are aliased; and arbitrarily-named
deployments resolve via a user-supplied ``BURNLENS_AZURE_DEPLOYMENTS`` map.
"""
from __future__ import annotations

import os
from typing import Optional

from burnlens.providers.base import ProviderConfig
from burnlens.providers.openai import OpenAIProvider

UPSTREAM_ENV = "BURNLENS_AZURE_ENDPOINT"
DEPLOYMENTS_ENV = "BURNLENS_AZURE_DEPLOYMENTS"

# Azure deployment names can't contain dots, so its gpt-3.5 family is spelled
# without them — map back to the canonical pricing keys in openai.json.
_AZURE_ALIASES = {
    "gpt-35-turbo": "gpt-3.5-turbo",
    "gpt-35-turbo-16k": "gpt-3.5-turbo-16k",
    "gpt-35-turbo-instruct": "gpt-3.5-turbo-instruct",
}


def _deployment_map() -> dict[str, str]:
    """User-supplied deployment->model map for deployments not named after
    their model, e.g. BURNLENS_AZURE_DEPLOYMENTS="prod-gpt4o=gpt-4o,cheap=gpt-4o-mini".
    Read at request time so it can be set without restarting the proxy.
    """
    out: dict[str, str] = {}
    for pair in os.environ.get(DEPLOYMENTS_ENV, "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


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
        deployment = request_body.get("model")
        if not deployment:
            parts = request_path.split("?", 1)[0].split("/")
            for i, part in enumerate(parts):
                if part == "deployments" and i + 1 < len(parts):
                    deployment = parts[i + 1]
                    break
        if not deployment:
            return None
        # Map the deployment name to a pricing key: user env map wins, then
        # Azure's dotless spellings, else the deployment name as-is (which
        # resolves when the deployment is named after its model, e.g. gpt-4o).
        mapping = {**_AZURE_ALIASES, **_deployment_map()}
        return mapping.get(deployment, deployment)


azure_provider = AzureOpenAIProvider()
