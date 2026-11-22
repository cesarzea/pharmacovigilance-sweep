"""Steps 1 and 2: screening and extraction, one record at a time, with validation and audit."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from . import validation as V
from .providers import ModelResult, Provider

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"

USER_TEMPLATE = "Channel: {channel}\nRecord date: {date}\nCountry: {country}\n-----\n{text}"


def load_prompt(name: str) -> tuple[str, dict, str]:
    text = (PROMPTS / f"{name}.md").read_text()
    schema_doc = json.loads((PROMPTS / f"{name}.schema.json").read_text())
    return text, schema_doc["schema"], f"{name}:{schema_doc['version']}"


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def audit_row(run_id, record_id, step, res: ModelResult, prompt_version, schema_version, user_text) -> dict:
    return {
        "call_id": uuid.uuid4().hex, "run_id": run_id, "record_id": record_id, "step": step,
        "provider": res.provider, "deployment": res.deployment, "prompt_version": prompt_version,
        "schema_version": schema_version, "input_hash": _hash(user_text), "output_hash": _hash(res.raw_text),
        "raw_output": json.dumps(res.output) if res.output is not None else json.dumps({"text": res.raw_text}),
        "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "cached_tokens": res.cached_tokens,
        "latency_ms": res.latency_ms, "status": res.status, "error": res.error,
    }


class Steps:
    def __init__(self, small: Provider, large: Provider | None, store, vocab: set[str] | None):
        self.small, self.large, self.store, self.vocab = small, large, store, vocab
        self.screen_prompt, self.screen_schema, self.screen_version = load_prompt("screening")
        self.extract_prompt, self.extract_schema, self.extract_version = load_prompt("extraction")
        self.screening_evidence: dict[str, tuple[list[str], str]] = {}   # record_id -> (evidence, confidence), for findings

    def user_text(self, rec: dict) -> str:
        return USER_TEMPLATE.format(channel=rec["channel_code"], date=rec["channel_received_date"],
                                    country=rec["country"], text=rec["record_text"])

    def screen(self, run_id: str, rec: dict) -> str:
        user = self.user_text(rec)
        res = self.small.structured(self.screen_prompt, user, self.screen_schema, "pvsweep_screening", max_tokens=600)
        problems = V.screening_problems(res.output, self.screen_schema, rec["record_text"]) if res.status == "ok" else [res.status]
        if res.status == "ok" and any(p.startswith("schema") or p == "no JSON object" for p in problems):
            res2 = self.small.structured(self.screen_prompt, user, self.screen_schema, "pvsweep_screening", max_tokens=600)
            self.store.insert_model_call(audit_row(run_id, rec["record_id"], "screen", res, self.screen_version, self.screen_version, user))
            res, problems = res2, (V.screening_problems(res2.output, self.screen_schema, rec["record_text"]) if res2.status == "ok" else [res2.status])
        self.store.insert_model_call(audit_row(run_id, rec["record_id"], "screen", res, self.screen_version, self.screen_version, user))
        if res.status != "ok" or any(p.startswith("schema") or p == "no JSON object" for p in problems):
            cls = "BLOCKED" if res.status == "blocked" else "INVALID"
            self.store.insert_screening(run_id, rec["record_id"], cls, {}, [], "low", {"status": res.status, "problems": problems})
            return cls
        out = res.output
        confidence = out["confidence"] if not problems else "low"   # unsupported evidence lowers confidence
        self.store.insert_screening(run_id, rec["record_id"], out["screening_class"], out["minimum_criteria"], out["evidence"],
                                    confidence, {**out, "problems": problems})
        self.screening_evidence[rec["record_id"]] = (list(out["evidence"]), confidence)
        return out["screening_class"]

    def extract(self, run_id: str, rec: dict) -> tuple[bool, dict | None]:
        user = self.user_text(rec)
        tier = "small"
        res = self.small.structured(self.extract_prompt, user, self.extract_schema, "pvsweep_extraction", max_tokens=2000)
        self.store.insert_model_call(audit_row(run_id, rec["record_id"], "extract", res, self.extract_version, self.extract_version, user))
        problems = V.extraction_problems(res.output, self.extract_schema, rec["record_text"], self.vocab) if res.status == "ok" else [res.status]
        hard = [p for p in problems if not p.startswith("uncoded")]
        if hard and self.large is not None:
            tier = "large"
            res = self.large.structured(self.extract_prompt, user, self.extract_schema, "pvsweep_extraction", max_tokens=2000)
            self.store.insert_model_call(audit_row(run_id, rec["record_id"], "extract", res, self.extract_version, self.extract_version, user))
            problems = V.extraction_problems(res.output, self.extract_schema, rec["record_text"], self.vocab) if res.status == "ok" else [res.status]
            hard = [p for p in problems if not p.startswith("uncoded")]
        valid = res.status == "ok" and not hard
        self.store.insert_extraction(run_id, rec["record_id"], res.output if res.output is not None else {"status": res.status},
                                     valid, problems, tier)
        return valid, (res.output if valid else None)
