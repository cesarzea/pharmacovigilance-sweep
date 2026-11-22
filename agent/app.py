"""Pharmacovigilance Sweep: hosted agent entry point (spike version).

Runs as a Foundry hosted agent behind the Invocations protocol (JSON in, JSON out). The same
image serves both providers; MODEL_PROVIDER selects the client:

    MODEL_PROVIDER=gpt     PVSWEEP_PROJECT_ENDPOINT, MODEL_DEPLOYMENT_NAME
    MODEL_PROVIDER=claude  PVSWEEP_FOUNDRY_RESOURCE, MODEL_DEPLOYMENT_NAME

The platform injects FOUNDRY_PROJECT_ENDPOINT itself (FOUNDRY_* and AGENT_* names are reserved),
so it is used when present and PVSWEEP_PROJECT_ENDPOINT is the local fallback.
Authentication is Entra ID only: the agent identity inside Foundry, DefaultAzureCredential locally.

Spike tools: `probe_url` proves outbound egress from the sandbox; `submit_result` is the terminal
tool pattern the matching agent will use.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Annotated

from agent_framework import Agent, tool
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

ENTRA_SCOPE = "https://ai.azure.com/.default"
INSTRUCTIONS = (
    "You are a connectivity and reasoning probe for a pharmacovigilance pipeline. "
    "Follow the user's request literally. When asked to probe a URL, call probe_url with it. "
    "Always finish by calling submit_result exactly once with a short summary, then reply with "
    "the JSON that submit_result returned and nothing else."
)


@tool(approval_mode="never_require")
def probe_url(url: Annotated[str, "HTTPS URL to request with GET"]) -> str:
    """Request a URL from inside the agent sandbox and report status and latency."""
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=15) as rsp:  # noqa: S310 - spike probe
            status = rsp.status
            body = rsp.read(200)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"url": url, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return json.dumps(
        {
            "url": url,
            "ok": True,
            "status": status,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "body_preview": body.decode("utf-8", "replace"),
        }
    )


@tool(approval_mode="never_require")
def submit_result(
    outcome: Annotated[str, "one of: ok, failed"],
    summary: Annotated[str, "one sentence"],
) -> str:
    """Terminal tool: records the agent's final structured result."""
    return json.dumps({"recorded": True, "outcome": outcome, "summary": summary})


def build_client():
    provider = os.environ.get("MODEL_PROVIDER", "gpt").lower()
    model = os.environ["MODEL_DEPLOYMENT_NAME"]
    credential = DefaultAzureCredential()
    if provider == "claude":
        from agent_framework.anthropic import AnthropicFoundryClient

        return AnthropicFoundryClient(
            resource=os.environ["PVSWEEP_FOUNDRY_RESOURCE"],
            model=model,
            azure_ad_token_provider=get_bearer_token_provider(credential, ENTRA_SCOPE),
        )
    from agent_framework.foundry import FoundryChatClient

    return FoundryChatClient(
        project_endpoint=os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or os.environ["PVSWEEP_PROJECT_ENDPOINT"],
        model=model,
        credential=credential,
    )


def build_agent() -> Agent:
    return Agent(
        client=build_client(),
        name=f"pvsweep-probe-{os.environ.get('MODEL_PROVIDER', 'gpt')}",
        instructions=INSTRUCTIONS,
        tools=[probe_url, submit_result],
    )


if __name__ == "__main__":
    from agent_framework_foundry_hosting import InvocationsHostServer

    InvocationsHostServer(build_agent).run(port=int(os.environ.get("PORT", "8088")))
