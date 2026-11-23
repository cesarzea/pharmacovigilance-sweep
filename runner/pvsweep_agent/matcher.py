"""Build and run the matching agent for one record.

`run_matching` returns the decision the agent submitted through `submit_match_decision`, together
with the log of every tool call, so the caller can check that each matched id came from a tool.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Annotated

from agent_framework import Agent, tool

from .backend import Backend

OUTCOMES = ("IN_SAFETY_DB", "SIGNIFICANT_FOLLOW_UP", "NON_SIGNIFICANT_FOLLOW_UP", "IN_INTAKE_QUEUE",
            "DUPLICATE_IN_SWEEP", "NO_MATCH")
MAX_TOOL_CALLS = 6
def _prompt_path() -> Path:
    """prompts/ sits two levels up in the repository (runner/pvsweep_agent) and one level up in the agent image (/app)."""
    here = Path(__file__).resolve()
    candidates = [Path(os.environ["PVSWEEP_PROMPTS_DIR"])] if os.environ.get("PVSWEEP_PROMPTS_DIR") else []
    candidates += [here.parents[2] / "prompts", here.parents[1] / "prompts"]
    for d in candidates:
        if (d / "matching.md").is_file():
            return d / "matching.md"
    raise FileNotFoundError(f"matching.md not found in {[str(c) for c in candidates]}")


PROMPT_PATH = _prompt_path()


def _json(rows) -> str:
    return json.dumps(rows, default=str, ensure_ascii=False)


class Context:
    """Per-invocation state: tool-call log, ids seen, the submitted decision."""

    def __init__(self):
        self.calls: list[dict] = []
        self.seen_ids: set[str] = set()
        self.decision: dict | None = None

    def log(self, name: str, args: dict, result):
        self.calls.append({"tool": name, "args": args, "rows": len(result) if isinstance(result, list) else None})


def make_tools(backend: Backend, ctx: Context, payload_ids: set[str]):
    ctx.seen_ids |= payload_ids

    @tool(approval_mode="never_require")
    def search_safety_cases(
        substance: Annotated[str, "active substance, lower case, e.g. sertraline"],
        sex: Annotated[str | None, "female, male or null"] = None,
        age_min: Annotated[float | None, "minimum age in years or null"] = None,
        age_max: Annotated[float | None, "maximum age in years or null"] = None,
        event_term: Annotated[str | None, "a Preferred Term-style name to rank by, or null"] = None,
        initials: Annotated[str | None, "patient initials to filter by, e.g. AB, or null"] = None,
        date_from: Annotated[str | None, "earliest receipt date YYYY-MM-DD or null"] = None,
        date_to: Annotated[str | None, "latest receipt date YYYY-MM-DD or null"] = None,
    ) -> str:
        """Search the safety database for cases with a suspect product of the given substance."""
        if len(ctx.calls) >= MAX_TOOL_CALLS:
            return _json({"error": "tool-call limit reached; submit your decision"})
        cols = ("case_id, patient_initials, initial_receipt_date, latest_receipt_date, event_date, case_version, reporter_type, "
                "age_years, sex, occurrence_country, serious, hospitalisation, death, substances, products, events")
        contains = {"duckdb": "list_contains(substances, ?)", "databricks": "array_contains(substances, ?)"}.get(
            backend.dialect, "ARRAY_CONTAINS(?::VARIANT, substances)")
        sql = f"SELECT {cols} FROM AGENT_API.SAFETY_CASE_SUMMARY WHERE {contains}"
        params: list = [substance.lower()]
        if initials:
            sql += " AND upper(patient_initials) = ?"
            params.append(initials.upper())
        if sex:
            sql += " AND (sex = ? OR sex = 'unknown')"
            params.append(sex)
        if age_min is not None:
            sql += " AND (age_years IS NULL OR age_years >= ?)"
            params.append(age_min)
        if age_max is not None:
            sql += " AND (age_years IS NULL OR age_years <= ?)"
            params.append(age_max)
        if date_from:
            sql += " AND latest_receipt_date >= ?"
            params.append(dt.date.fromisoformat(date_from))
        if date_to:
            sql += " AND latest_receipt_date <= ?"
            params.append(dt.date.fromisoformat(date_to))
        sql += " LIMIT 40"
        rows = backend.rows(sql, params)
        if event_term:
            t = event_term.lower()
            rows.sort(key=lambda r: 0 if any(t == str(e).lower() for e in (r.get("events") or [])) else 1)
        rows = rows[:15]
        ctx.seen_ids |= {r["case_id"] for r in rows}
        ctx.log("search_safety_cases", {"substance": substance, "sex": sex, "age_min": age_min, "age_max": age_max,
                                        "event_term": event_term, "initials": initials, "date_from": date_from, "date_to": date_to}, rows)
        return _json(rows)

    @tool(approval_mode="never_require")
    def get_case_history(case_id: Annotated[str, "a case id returned by search_safety_cases"]) -> str:
        """Versions of a safety case and what each one added."""
        if len(ctx.calls) >= MAX_TOOL_CALLS:
            return _json({"error": "tool-call limit reached; submit your decision"})
        rows = backend.rows("SELECT case_id, case_version, received_date, significant, information_summary FROM AGENT_API.CASE_HISTORY "
                            "WHERE case_id = ? ORDER BY case_version", [case_id])
        ctx.log("get_case_history", {"case_id": case_id}, rows)
        return _json(rows or [{"note": "no version history recorded for this case"}])

    @tool(approval_mode="never_require")
    def search_intake_queue(
        text: Annotated[str | None, "words to look for in the queue summaries (product, substance, event, sex, age); "
                                    "every word of 4+ letters must appear; or null when intake_id is given"] = None,
        intake_id: Annotated[str | None, "an intake id from the payload, to fetch that item directly"] = None,
        date_from: Annotated[str | None, "earliest PV receipt date YYYY-MM-DD or null"] = None,
        date_to: Annotated[str | None, "latest PV receipt date YYYY-MM-DD or null"] = None,
    ) -> str:
        """Items received by pharmacovigilance that are not cases yet."""
        if len(ctx.calls) >= MAX_TOOL_CALLS:
            return _json({"error": "tool-call limit reached; submit your decision"})
        sql = ("SELECT intake_id, channel_code, vendor_reference, received_by_pv, status, case_id, summary "
               "FROM AGENT_API.INTAKE_QUEUE WHERE 1 = 1")
        params: list = []
        if intake_id:
            sql += " AND intake_id = ?"
            params.append(intake_id)
        else:
            tokens = [t for t in re.split(r"[,\s]+", (text or "").lower()) if len(t) >= 4]
            if not tokens:
                return _json({"error": "give an intake_id or at least one word of 4+ letters"})
            for t in tokens:
                sql += " AND lower(summary) LIKE ?"
                params.append(f"%{t}%")
        if date_from:
            sql += " AND received_by_pv >= ?"
            params.append(dt.datetime.fromisoformat(date_from))
        if date_to:
            sql += " AND received_by_pv < ?"
            params.append(dt.datetime.fromisoformat(date_to) + dt.timedelta(days=1))
        rows = backend.rows(sql + " LIMIT 20", params)
        ctx.seen_ids |= {r["intake_id"] for r in rows}
        ctx.log("search_intake_queue", {"text": text, "intake_id": intake_id, "date_from": date_from, "date_to": date_to}, rows)
        return _json(rows)

    @tool(approval_mode="never_require")
    def search_intake_log(
        vendor_code: Annotated[str, "PSPV, MIV or SOCV"],
        vendor_reference: Annotated[str, "the vendor's reference number"],
    ) -> str:
        """Pharmacovigilance's own log of what it received from a vendor, by vendor reference."""
        if len(ctx.calls) >= MAX_TOOL_CALLS:
            return _json({"error": "tool-call limit reached; submit your decision"})
        rows = backend.rows("SELECT intake_id, vendor_code, vendor_reference, received_by_pv, product_name, event_summary "
                            "FROM AGENT_API.INTAKE_LOG WHERE vendor_code = ? AND vendor_reference = ? LIMIT 20",
                            [vendor_code, vendor_reference])
        ctx.seen_ids |= {f"{r['intake_id']}" for r in rows}
        ctx.log("search_intake_log", {"vendor_code": vendor_code, "vendor_reference": vendor_reference}, rows)
        return _json(rows)

    @tool(approval_mode="never_require")
    def search_vendor_log(
        vendor_code: Annotated[str, "PSPV, MIV or SOCV"],
        vendor_reference: Annotated[str | None, "the vendor's reference number, or null to list by product"] = None,
        product_name: Annotated[str | None, "product name to filter by when no reference"] = None,
    ) -> str:
        """What a vendor says it forwarded to pharmacovigilance."""
        if len(ctx.calls) >= MAX_TOOL_CALLS:
            return _json({"error": "tool-call limit reached; submit your decision"})
        sql = "SELECT vendor_code, vendor_reference, sent_at, product_name, event_summary FROM AGENT_API.VENDOR_TX_LOG WHERE vendor_code = ?"
        params: list = [vendor_code]
        if vendor_reference:
            sql += " AND vendor_reference = ?"
            params.append(vendor_reference)
        elif product_name:
            sql += " AND lower(product_name) = ?"
            params.append(product_name.lower())
        rows = backend.rows(sql + " LIMIT 20", params)
        ctx.seen_ids |= {f"{r['vendor_code']}/{r['vendor_reference']}" for r in rows}
        ctx.log("search_vendor_log", {"vendor_code": vendor_code, "vendor_reference": vendor_reference, "product_name": product_name}, rows)
        return _json(rows)

    @tool(approval_mode="never_require")
    def submit_match_decision(
        outcome: Annotated[str, "one of IN_SAFETY_DB, SIGNIFICANT_FOLLOW_UP, NON_SIGNIFICANT_FOLLOW_UP, IN_INTAKE_QUEUE, DUPLICATE_IN_SWEEP, NO_MATCH"],
        matched_ids: Annotated[list[str], "case ids, intake ids or vendor references (vendor/reference) that match; empty for NO_MATCH"],
        new_facts: Annotated[list[str], "for SIGNIFICANT_FOLLOW_UP: the new facts, each quoted from the record"],
        justification: Annotated[str, "two or three sentences a reviewer can check"],
        confidence: Annotated[str, "high, medium or low"],
    ) -> str:
        """Record the final decision. Call exactly once."""
        unknown = [i for i in matched_ids if i not in ctx.seen_ids]
        if outcome not in OUTCOMES:
            return _json({"accepted": False, "error": f"outcome must be one of {OUTCOMES}"})
        if unknown:
            return _json({"accepted": False, "error": f"ids not returned by any tool or the payload: {unknown}; search for them or drop them"})
        if outcome != "NO_MATCH" and not matched_ids:
            return _json({"accepted": False, "error": "this outcome needs at least one matched id"})
        ctx.decision = {"outcome": outcome, "matched_ids": matched_ids, "new_facts": new_facts,
                        "justification": justification, "confidence": confidence}
        return _json({"accepted": True, **ctx.decision, "tool_calls": ctx.calls})

    return [search_safety_cases, get_case_history, search_intake_queue, search_intake_log, search_vendor_log,
            submit_match_decision]


def payload_ids(payload: dict) -> set[str]:
    return {c["candidate_id"] for c in payload.get("candidates", [])} | {d["record_id"] for d in payload.get("sweep_duplicates", [])}


async def run_matching(client, backend: Backend, payload: dict, name: str = "pvsweep-matcher") -> dict:
    """payload: {"record": {...extraction and metadata...}, "candidates": [...], "sweep_duplicates": [...]}"""
    ctx = Context()
    agent = Agent(client=client, name=name, instructions=PROMPT_PATH.read_text(),
                  tools=make_tools(backend, ctx, payload_ids(payload)))
    message = "Potential case and candidates (JSON):\n" + json.dumps(payload, default=str, ensure_ascii=False)
    response = await agent.run(message)
    if ctx.decision is None:
        # One more chance: ask for the submission explicitly.
        response = await agent.run(message + "\n\nYou did not call submit_match_decision. Call it now with your decision.")
    decision = ctx.decision or {"outcome": "BLOCKED", "matched_ids": [], "new_facts": [], "justification": "agent did not submit a decision",
                                "confidence": "low"}
    decision["tool_calls"] = ctx.calls
    decision["submitted"] = ctx.decision is not None
    decision["reply_text"] = response.text
    usage = getattr(response, "usage_details", None)
    decision["usage"] = {
        "input_tokens": getattr(usage, "input_token_count", None) or 0,
        "output_tokens": getattr(usage, "output_token_count", None) or 0,
        "total_tokens": getattr(usage, "total_token_count", None) or 0,
    }
    return decision
