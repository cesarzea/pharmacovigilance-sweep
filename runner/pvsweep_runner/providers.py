"""Model providers behind one interface: structured JSON out, usage and latency in.

Both providers run in Microsoft Foundry with Entra ID. The same system prompt, user text and JSON
schema go to each; the only difference is the transport (Responses API for GPT, Messages API for
Claude). Nothing here retries on validation errors; the steps decide what to do with a bad answer.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from azure.identity import DefaultAzureCredential, get_bearer_token_provider

ENTRA_SCOPE = "https://ai.azure.com/.default"


@dataclass
class ModelResult:
    provider: str
    deployment: str
    output: dict | None
    raw_text: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    latency_ms: int
    status: str          # ok | invalid_json | blocked | error
    error: str | None = None


class Provider:
    name: str

    def structured(self, system: str, user: str, schema: dict, schema_name: str, max_tokens: int = 2048) -> ModelResult:
        raise NotImplementedError


def _token_provider():
    return get_bearer_token_provider(DefaultAzureCredential(), ENTRA_SCOPE)


class GptFoundry(Provider):
    name = "gpt"

    def __init__(self, account: str, deployment: str):
        from openai import OpenAI

        self.deployment = deployment
        self._tokens = _token_provider()
        self._client = OpenAI(base_url=f"https://{account}.services.ai.azure.com/openai/v1/", api_key=self._tokens(),
                              max_retries=5)

    def structured(self, system, user, schema, schema_name, max_tokens=2048):
        self._client.api_key = self._tokens()
        t0 = time.perf_counter()
        try:
            rsp = self._client.responses.create(
                model=self.deployment,
                instructions=system,
                input=user,
                max_output_tokens=max_tokens,
                text={"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
            )
        except Exception as exc:  # noqa: BLE001
            return ModelResult(self.name, self.deployment, None, "", 0, 0, 0,
                               round((time.perf_counter() - t0) * 1000), _classify(exc), f"{type(exc).__name__}: {exc}")
        ms = round((time.perf_counter() - t0) * 1000)
        u = rsp.usage
        cached = (u.input_tokens_details.cached_tokens if u and u.input_tokens_details else 0) or 0
        text = rsp.output_text or ""
        if rsp.status != "completed" or any(getattr(o, "type", "") == "refusal" for o in rsp.output):
            return ModelResult(self.name, self.deployment, None, text, u.input_tokens, u.output_tokens, cached, ms, "blocked",
                               f"status={rsp.status}")
        try:
            return ModelResult(self.name, self.deployment, json.loads(text), text, u.input_tokens, u.output_tokens, cached, ms, "ok")
        except ValueError as exc:
            return ModelResult(self.name, self.deployment, None, text, u.input_tokens, u.output_tokens, cached, ms, "invalid_json", str(exc))


class ClaudeFoundry(Provider):
    name = "claude"

    def __init__(self, account: str, deployment: str):
        from anthropic import AnthropicFoundry

        self.deployment = deployment
        self._client = AnthropicFoundry(resource=account, azure_ad_token_provider=_token_provider(), max_retries=5)

    def structured(self, system, user, schema, schema_name, max_tokens=2048):
        t0 = time.perf_counter()
        try:
            msg = self._client.messages.create(
                model=self.deployment,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except Exception as exc:  # noqa: BLE001
            return ModelResult(self.name, self.deployment, None, "", 0, 0, 0,
                               round((time.perf_counter() - t0) * 1000), _classify(exc), f"{type(exc).__name__}: {exc}")
        ms = round((time.perf_counter() - t0) * 1000)
        u = msg.usage
        cached = getattr(u, "cache_read_input_tokens", 0) or 0
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        if msg.stop_reason == "refusal":
            return ModelResult(self.name, self.deployment, None, text, u.input_tokens, u.output_tokens, cached, ms, "blocked",
                               "stop_reason=refusal")
        try:
            return ModelResult(self.name, self.deployment, json.loads(text), text, u.input_tokens, u.output_tokens, cached, ms, "ok")
        except ValueError as exc:
            return ModelResult(self.name, self.deployment, None, text, u.input_tokens, u.output_tokens, cached, ms, "invalid_json", str(exc))


class ClaudeDirect(ClaudeFoundry):
    """Anthropic API with the user's own key (ANTHROPIC_API_KEY from .env). Development and synthetic
    data only: the evaluated path is Claude on Foundry (docs/ops/spike-log.md)."""

    name = "claude-direct"

    def __init__(self, deployment: str):  # noqa: D107 - deployment is the model id here
        from anthropic import Anthropic

        from .env import load_dotenv

        load_dotenv()
        self.deployment = deployment
        self._client = Anthropic(max_retries=5, default_headers=anthropic_headers())


def anthropic_headers() -> dict:
    """An organisation-level key must name the workspace; a workspace-scoped key needs nothing."""
    import os

    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    return {"anthropic-workspace-id": ws} if ws else {}


def _classify(exc: Exception) -> str:
    text = str(exc).lower()
    if "content_filter" in text or "content management policy" in text or "refusal" in text:
        return "blocked"
    return "error"


def make_provider(provider: str, account: str, deployment: str) -> Provider:
    if provider == "gpt":
        return GptFoundry(account, deployment)
    if provider == "claude":
        return ClaudeFoundry(account, deployment)
    if provider == "claude-direct":
        return ClaudeDirect(deployment)
    raise ValueError(provider)
