"""Checks applied to every model answer before it is stored (docs/architecture.md, section 6)."""

from __future__ import annotations

import re

import jsonschema

_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def schema_problems(obj: dict | None, schema: dict) -> list[str]:
    if obj is None:
        return ["no JSON object"]
    v = jsonschema.Draft202012Validator(schema)
    return [f"schema: {e.message} at {'/'.join(str(p) for p in e.path)}" for e in v.iter_errors(obj)]


def evidence_problems(spans: list[str | None], record_text: str, label: str) -> list[str]:
    """Each span must appear verbatim. Surrounding quotes are ignored; an ellipsis splits a span into
    pieces that must each appear, in order."""
    body = normalise(record_text)
    out = []
    for span in spans:
        if not span:
            continue
        s = normalise(span).strip("\"'“”‘’ ")
        pieces = [p.strip("\"'“”‘’ ") for p in re.split(r"\s*(?:\.\.\.|…)\s*", s) if p.strip()]
        pos = 0
        for piece in pieces:
            idx = body.find(piece, pos)
            if idx < 0:
                out.append(f"{label}: evidence not found verbatim: {span[:60]!r}")
                break
            pos = idx + len(piece)
    return out


def screening_problems(obj: dict | None, schema: dict, record_text: str) -> list[str]:
    problems = schema_problems(obj, schema)
    if problems:
        return problems
    return evidence_problems(obj.get("evidence", []), record_text, "screening")


def extraction_problems(obj: dict | None, schema: dict, record_text: str, vocab: set[str] | None) -> list[str]:
    problems = schema_problems(obj, schema)
    if problems:
        return problems
    spans = [obj["patient"].get("evidence"), obj["reporter"].get("evidence"), obj["causality_statement"].get("evidence")]
    spans += [p.get("evidence") for p in obj["products"]]
    spans += [e.get("evidence") for e in obj["events"]]
    problems += evidence_problems(spans, record_text, "extraction")
    if vocab is not None:
        for e in obj["events"]:
            if e["proposed_term"].strip().lower() not in vocab:
                problems.append(f"uncoded: term not in vocabulary: {e['proposed_term']!r}")
    return problems
