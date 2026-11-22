"""Pharmacovigilance Sweep: hosted agent entry point (Foundry Agent Service, Invocations protocol).

The Invocations message is the matching payload as a JSON string. The reply is the JSON returned by
`submit_match_decision` (decision plus tool-call log), which the runner validates and stores.

Environment (FOUNDRY_* and AGENT_* names are reserved by the platform):
    MODEL_PROVIDER=gpt|claude   MODEL_DEPLOYMENT_NAME   PVSWEEP_PROJECT_ENDPOINT   PVSWEEP_FOUNDRY_RESOURCE
    PVSWEEP_SNOWFLAKE_ACCOUNT   PVSWEEP_SNOWFLAKE_PRIVATE_KEY (injected from a Foundry connection)
Authentication is Entra ID for the models (the agent identity) and key-pair for Snowflake.
"""

from __future__ import annotations

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

    client = _client()
    state: dict = {}

    @tool(approval_mode="never_require")
    async def match(payload_json: str) -> str:
        """Run the matching agent on the JSON payload and return its decision JSON."""
        # Async on purpose: the host runs tools inside its own event loop, where asyncio.run() is not allowed.
        try:
            if "backend" not in state:
                state["backend"] = from_env()  # Snowflake connection, opened on first use so start-up never fails
            payload = json.loads(payload_json)
            decision = await run_matching(client, state["backend"], payload, name=f"pvsweep-matcher-{PROVIDER}")
            return json.dumps(decision, default=str)
        except Exception as exc:  # noqa: BLE001 - the runner records the reason as a BLOCKED decision
            key = os.environ.get("PVSWEEP_SNOWFLAKE_PRIVATE_KEY", "")
            return json.dumps({"error": f"{type(exc).__name__}: {str(exc)[:300]}",
                               "snowflake_account_set": bool(os.environ.get("PVSWEEP_SNOWFLAKE_ACCOUNT")),
                               "snowflake_key_is_pem": key.startswith("-----BEGIN"), "snowflake_key_chars": len(key)})

    return Agent(client=client, name=f"pvsweep-matcher-{PROVIDER}", tools=[match],
                 instructions="The user message is a JSON payload. Call match with it exactly once and reply with the "
                              "tool's output verbatim, nothing else.")


if __name__ == "__main__":
    from agent_framework_foundry_hosting import InvocationsHostServer

    InvocationsHostServer(build_agent).run(port=int(os.environ.get("PORT", "8088")))
