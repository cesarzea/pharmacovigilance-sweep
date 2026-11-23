"""Pharmacovigilance Sweep: hosted agent entry point (Foundry Agent Service, Invocations protocol).

The Invocations message is the matching payload as a JSON string. The reply is the JSON returned by
`submit_match_decision` (decision plus tool-call log), which the runner validates and stores.

The host expects an object that satisfies Agent Framework's `SupportsAgentRun` protocol. `MatcherAgent`
implements it directly and hands the message to the matcher, so no model has to echo a 10,000-token
payload into a tool call (which is where a wrapper Agent with a `match` tool broke on Claude: the
tool-call argument exceeded the client's output budget).

Environment (FOUNDRY_* and AGENT_* names are reserved by the platform):
    MODEL_PROVIDER=gpt|claude   MODEL_DEPLOYMENT_NAME   PVSWEEP_PROJECT_ENDPOINT   PVSWEEP_FOUNDRY_RESOURCE
    PVSWEEP_SNOWFLAKE_ACCOUNT   PVSWEEP_SNOWFLAKE_PRIVATE_KEY (resolved from a Foundry project connection)
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
NAME = f"pvsweep-matcher-{PROVIDER}"


def _client():
    return make_client(
        PROVIDER, os.environ["MODEL_DEPLOYMENT_NAME"],
        project_endpoint=os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or os.environ.get("PVSWEEP_PROJECT_ENDPOINT"),
        resource=os.environ.get("PVSWEEP_FOUNDRY_RESOURCE"),
    )


class MatcherAgent:
    """Runs the matching agent on the incoming payload; one invocation, one decision, no memory."""

    def __init__(self):
        self.id = NAME
        self.name = NAME
        self.description = f"Pharmacovigilance Sweep matching agent on {PROVIDER}"
        self.client = _client()
        self._backend = None

    async def _decide(self, messages) -> str:
        try:
            if self._backend is None:
                self._backend = from_env()  # Snowflake connection, opened on first use so start-up never fails
            if isinstance(messages, str):
                text = messages
            else:
                msgs = messages if isinstance(messages, (list, tuple)) else [messages]
                text = "\n".join(getattr(m, "text", None) or str(m) for m in msgs)
            payload = json.loads(text)
            for attempt in range(4):  # model quota (HTTP 429) is the one transient failure worth waiting out in the sandbox
                try:
                    decision = await run_matching(self.client, self._backend, payload, name=NAME)
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 3 or not ("429" in str(exc) or "rate_limit" in str(exc).lower()):
                        raise
                    await asyncio.sleep(20 * (attempt + 1))
            return json.dumps(decision, default=str)
        except Exception as exc:  # noqa: BLE001 - the runner records the reason as a BLOCKED decision
            key = os.environ.get("PVSWEEP_SNOWFLAKE_PRIVATE_KEY", "")
            return json.dumps({"error": f"{type(exc).__name__}: {str(exc)[:300]}",
                               "snowflake_account_set": bool(os.environ.get("PVSWEEP_SNOWFLAKE_ACCOUNT")),
                               "snowflake_key_is_pem": key.startswith("-----BEGIN"), "snowflake_key_chars": len(key)})

    def run(self, messages=None, *, stream: bool = False, session=None, **kwargs):
        from agent_framework import AgentResponse, AgentResponseUpdate, Message

        async def _run():
            reply = Message("assistant", [await self._decide(messages)])
            return AgentResponse(messages=[reply], agent_id=self.id)

        async def _stream():
            reply = Message("assistant", [await self._decide(messages)])
            yield AgentResponseUpdate(contents=reply.contents, role="assistant", agent_id=self.id)

        return _stream() if stream else _run()

    def create_session(self, *, session_id: str | None = None):
        from agent_framework import AgentSession

        return AgentSession(session_id=session_id)

    def get_session(self, service_session_id, *, session_id: str | None = None):
        from agent_framework import AgentSession

        return AgentSession(service_session_id=service_session_id, session_id=session_id)


def build_agent():
    return MatcherAgent()


if __name__ == "__main__":
    from agent_framework_foundry_hosting import InvocationsHostServer

    InvocationsHostServer(build_agent).run(port=int(os.environ.get("PORT", "8088")))
