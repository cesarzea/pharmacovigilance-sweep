"""Pharmacovigilance Sweep: hosted agent entry point (Foundry Agent Service, Invocations protocol).

The Invocations message is the matching payload as a JSON string. The reply is the JSON returned by
`submit_match_decision` (decision plus tool-call log), which the runner validates and stores.

Environment (FOUNDRY_* and AGENT_* names are reserved by the platform):
    MODEL_PROVIDER=gpt|claude   MODEL_DEPLOYMENT_NAME   PVSWEEP_PROJECT_ENDPOINT   PVSWEEP_FOUNDRY_RESOURCE
    PVSWEEP_SNOWFLAKE_ACCOUNT   PVSWEEP_SNOWFLAKE_PRIVATE_KEY (injected from a Foundry connection)
Authentication is Entra ID for the models (the agent identity) and key-pair for Snowflake.
"""

from __future__ import annotations

import asyncio
import json
import os

from pvsweep_agent.backend import from_env
from pvsweep_agent.clients import make_client
from pvsweep_agent.matcher import run_matching

PROVIDER = os.environ.get("MODEL_PROVIDER", "gpt").lower()


def _client():
    return make_client(
        PROVIDER, os.environ["MODEL_DEPLOYMENT_NAME"],
        project_endpoint=os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or os.environ.get("PVSWEEP_PROJECT_ENDPOINT"),
        resource=os.environ.get("PVSWEEP_FOUNDRY_RESOURCE"),
    )


def build_agent():
    """A thin Agent whose single tool runs the matcher: keeps the host's Invocations contract simple."""
    from agent_framework import Agent, tool

    backend = from_env()
    client = _client()

    @tool(approval_mode="never_require")
    def match(payload_json: str) -> str:
        """Run the matching agent on the JSON payload and return its decision JSON."""
        payload = json.loads(payload_json)
        decision = asyncio.run(run_matching(client, backend, payload, name=f"pvsweep-matcher-{PROVIDER}"))
        return json.dumps(decision, default=str)

    return Agent(client=client, name=f"pvsweep-matcher-{PROVIDER}", tools=[match],
                 instructions="The user message is a JSON payload. Call match with it exactly once and reply with the "
                              "tool's output verbatim, nothing else.")


if __name__ == "__main__":
    from agent_framework_foundry_hosting import InvocationsHostServer

    InvocationsHostServer(build_agent).run(port=int(os.environ.get("PORT", "8088")))
