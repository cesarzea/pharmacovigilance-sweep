"""Step 4: matching, three ways.

- agent: the Agent Framework matching agent run in-process (same package as the hosted agent).
- hosted: the hosted agent in Foundry Agent Service through the Invocations endpoint.
- baseline: one structured call over the blocked candidates only, for the agent-vs-single-call comparison.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx

from .providers import Provider

BASELINE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome", "matched_ids", "new_facts", "justification", "confidence"],
    "properties": {
        "outcome": {"type": "string", "enum": ["IN_SAFETY_DB", "SIGNIFICANT_FOLLOW_UP", "NON_SIGNIFICANT_FOLLOW_UP",
                                               "IN_INTAKE_QUEUE", "DUPLICATE_IN_SWEEP", "NO_MATCH"]},
        "matched_ids": {"type": "array", "items": {"type": "string"}},
        "new_facts": {"type": "array", "items": {"type": "string"}},
        "justification": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}


def build_payload(rec: dict, extraction: dict, rule: dict, candidates: list[dict], sweep_duplicates: list[dict]) -> dict:
    return {
        "record": {
            "record_id": rec["record_id"], "channel": rec["channel_code"], "channel_received_date": str(rec["channel_received_date"]),
            "country": rec["country"], "vendor_code": rec.get("vendor_code"), "vendor_reference": rec.get("vendor_reference"),
            "substance": rule.get("substance"), "ownership": rule.get("ownership"),
            "patient": extraction.get("patient"), "reporter": extraction.get("reporter"), "products": extraction.get("products"),
            "events": extraction.get("events"), "seriousness": extraction.get("seriousness"),
            "causality_statement": extraction.get("causality_statement"), "event_context": extraction.get("event_context"),
            "dates": extraction.get("dates"),
        },
        "candidates": candidates,
        "sweep_duplicates": sweep_duplicates,
    }


def validate_decision(decision: dict, payload: dict) -> tuple[bool, list[str]]:
    """Every matched id must come from the payload or a tool result."""
    known = {c["candidate_id"] for c in payload["candidates"]} | {d["record_id"] for d in payload["sweep_duplicates"]}
    tool_ids: set[str] = set(decision.get("tool_ids", []))
    problems = []
    if not decision.get("submitted", True):
        problems.append("no decision submitted")
    for i in decision.get("matched_ids", []):
        if i not in known and i not in tool_ids and not decision.get("tool_calls"):
            problems.append(f"id not from payload: {i}")
    if decision.get("outcome") != "NO_MATCH" and not decision.get("matched_ids"):
        problems.append("outcome without matched ids")
    return not problems, problems


def match_baseline(provider: Provider, prompt: str, payload: dict) -> dict:
    user = "Potential case and candidates (JSON):\n" + json.dumps(payload, default=str, ensure_ascii=False)
    res = provider.structured(prompt + "\n\nYou have no tools in this mode: decide from the candidates given.",
                              user, BASELINE_SCHEMA, "pvsweep_match", max_tokens=800)
    if res.status != "ok" or res.output is None:
        return {"outcome": "BLOCKED", "matched_ids": [], "new_facts": [], "justification": res.error or res.status,
                "confidence": "low", "tool_calls": [], "submitted": False, "_model": res}
    return {**res.output, "tool_calls": [], "submitted": True, "_model": res}


class AgentRunner:
    """One long-lived event loop in its own thread: the framework's async client is bound to a loop,
    so worker threads submit coroutines to it instead of calling asyncio.run each time."""

    def __init__(self, client_factory):
        import threading

        self.loop = asyncio.new_event_loop()
        self._client = None
        self._factory = client_factory
        threading.Thread(target=self.loop.run_forever, daemon=True, name="agent-loop").start()

    async def _run(self, backend, payload, name):
        from pvsweep_agent.matcher import run_matching

        if self._client is None:
            self._client = self._factory()
        return await run_matching(self._client, backend, payload, name=name)

    def match(self, backend, payload: dict, name: str) -> dict:
        t0 = time.perf_counter()
        for backoff in (15, 30, 60, 120, 180):
            try:
                decision = asyncio.run_coroutine_threadsafe(self._run(backend, payload, name), self.loop).result(timeout=600)
                break
            except Exception as exc:  # noqa: BLE001 - the framework wraps provider errors
                if "429" not in str(exc) and "rate limit" not in str(exc).lower():
                    # Refusals, invalidated streams, transport errors: the record goes to human review.
                    decision = {"outcome": "BLOCKED", "matched_ids": [], "new_facts": [], "confidence": "low",
                                "justification": f"agent failed: {type(exc).__name__}: {str(exc)[:300]}",
                                "tool_calls": [], "submitted": False}
                    break
                time.sleep(backoff)
        else:
            decision = {"outcome": "BLOCKED", "matched_ids": [], "new_facts": [], "justification": "rate limited five times",
                        "confidence": "low", "tool_calls": [], "submitted": False}
        decision["latency_ms"] = round((time.perf_counter() - t0) * 1000)
        return decision


# Hosted sessions: a sandbox costs about six seconds to start and one second to reuse (spike item 4), so
# each agent keeps a pool of free session ids. A call takes one (or starts a new session when none is
# free) and returns it afterwards, so at most `concurrency` sessions exist per agent. The hosted agent
# keeps no state between invocations, so reuse cannot leak one record into the next.
_SESSION_POOL: dict[str, list[str]] = {}
_SESSION_LOCK = threading.Lock()


def _take_session(agent_name: str) -> str | None:
    with _SESSION_LOCK:
        free = _SESSION_POOL.setdefault(agent_name, [])
        return free.pop() if free else None


def _give_session(agent_name: str, session_id: str | None) -> None:
    if session_id:
        with _SESSION_LOCK:
            _SESSION_POOL.setdefault(agent_name, []).append(session_id)


def match_hosted(project_endpoint: str, agent_name: str, token: str, payload: dict, timeout: float = 300) -> dict:
    url = f"{project_endpoint}/agents/{agent_name}/endpoint/protocols/invocations"
    params = {"api-version": "v1"}
    session_id = _take_session(agent_name)
    if session_id:
        params["agent_session_id"] = session_id  # the platform reads the session id from the query string only
    t0 = time.perf_counter()
    rsp = None
    for attempt in range(3):  # transient TLS/connection errors on the client side; the sandbox is not involved yet
        try:
            rsp = httpx.post(url, params=params, headers={"Authorization": f"Bearer {token}"},
                             json={"message": json.dumps(payload, default=str)}, timeout=timeout)
            break
        except httpx.TransportError as exc:
            last_exc = exc
            time.sleep(2 * (attempt + 1))
    if rsp is None:
        _give_session(agent_name, session_id)
        ms = round((time.perf_counter() - t0) * 1000)
        return {"outcome": "BLOCKED", "matched_ids": [], "new_facts": [], "justification": f"transport error: {type(last_exc).__name__}: {str(last_exc)[:160]}",
                "confidence": "low", "tool_calls": [], "submitted": False, "latency_ms": ms}
    _give_session(agent_name, rsp.headers.get("x-agent-session-id") or session_id)
    ms = round((time.perf_counter() - t0) * 1000)
    if not rsp.is_success:
        return {"outcome": "BLOCKED", "matched_ids": [], "new_facts": [], "justification": f"HTTP {rsp.status_code}: {rsp.text[:200]}",
                "confidence": "low", "tool_calls": [], "submitted": False, "latency_ms": ms}
    text = rsp.json().get("response", "")
    try:
        start = text.index("{")
        decision = json.loads(text[start:text.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {"outcome": "BLOCKED", "matched_ids": [], "new_facts": [], "justification": f"unparseable reply: {text[:200]}",
                "confidence": "low", "tool_calls": [], "submitted": False, "latency_ms": ms}
    decision.setdefault("submitted", decision.get("accepted", True))
    decision["latency_ms"] = ms
    decision["session_id"] = rsp.headers.get("x-agent-session-id")
    return decision
