"""Spike 1: call Claude and GPT on Microsoft Foundry with Entra ID only (no API keys).

Usage:
    uv run --with anthropic --with openai --with azure-identity python -I spike/01_entra_model_calls.py \
        --account <foundry-account-name> --claude claude-haiku-5-5 --gpt gpt-5-4-mini

Both calls ask for a strict JSON answer so the structured-output path is exercised too.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from anthropic import AnthropicFoundry
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI

SCOPE = "https://ai.azure.com/.default"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_adverse_event", "events", "confidence"],
    "properties": {
        "is_adverse_event": {"type": "boolean"},
        "events": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}

TEXT = (
    "PSP nurse call note: patient on Contoso-brand escitalopram 10 mg since March. "
    "Admitted to hospital on Monday for an arrhythmia; discharged Wednesday. No cause mentioned."
)

PROMPT = (
    "You screen pharmacovigilance source records. Return JSON only, following the schema. "
    "is_adverse_event is true when the text describes an untoward medical occurrence in a person "
    "exposed to a medicinal product, whether or not anyone links it to the product.\n\nRecord:\n" + TEXT
)


def call_claude(account: str, deployment: str, token_provider) -> dict:
    client = AnthropicFoundry(resource=account, azure_ad_token_provider=token_provider)
    t0 = time.perf_counter()
    msg = client.messages.create(
        model=deployment,
        max_tokens=1024,
        messages=[{"role": "user", "content": PROMPT}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    ms = round((time.perf_counter() - t0) * 1000)
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return {
        "provider": "claude",
        "deployment": deployment,
        "latency_ms": ms,
        "stop_reason": msg.stop_reason,
        "usage": msg.usage.model_dump(exclude_none=True),
        "output": json.loads(text),
    }


def call_gpt(account: str, deployment: str, token_provider) -> dict:
    client = OpenAI(
        base_url=f"https://{account}.services.ai.azure.com/openai/v1/",
        api_key=token_provider(),
    )
    t0 = time.perf_counter()
    rsp = client.responses.create(
        model=deployment,
        input=PROMPT,
        text={
            "format": {
                "type": "json_schema",
                "name": "screening",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    )
    ms = round((time.perf_counter() - t0) * 1000)
    return {
        "provider": "gpt",
        "deployment": deployment,
        "latency_ms": ms,
        "status": rsp.status,
        "usage": rsp.usage.model_dump(exclude_none=True) if rsp.usage else None,
        "output": json.loads(rsp.output_text),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--claude", default="claude-haiku-5-5")
    ap.add_argument("--gpt", default="gpt-5-4-mini")
    args = ap.parse_args()

    token_provider = get_bearer_token_provider(DefaultAzureCredential(), SCOPE)
    failures = 0
    for name, fn, dep in (("claude", call_claude, args.claude), ("gpt", call_gpt, args.gpt)):
        if not dep:
            continue
        try:
            print(json.dumps(fn(args.account, dep, token_provider), indent=2))
        except Exception as exc:  # noqa: BLE001 - spike: report everything
            failures += 1
            print(f"{name}: FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
