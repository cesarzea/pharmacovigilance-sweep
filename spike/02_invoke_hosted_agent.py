"""Spike 2: invoke a hosted agent through the Invocations protocol with Entra ID.

    uv run --with azure-identity --with httpx python -I spike/02_invoke_hosted_agent.py \
        --project-endpoint https://<account>.services.ai.azure.com/api/projects/<project> \
        --agent pvsweep-matcher-gpt --message "Probe https://example.com and submit the result."
"""

from __future__ import annotations

import argparse
import json
import time

import httpx
from azure.identity import DefaultAzureCredential


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-endpoint", required=True)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--message", required=True)
    ap.add_argument("--timeout", type=float, default=300)
    args = ap.parse_args()

    token = DefaultAzureCredential().get_token("https://ai.azure.com/.default").token
    url = f"{args.project_endpoint}/agents/{args.agent}/endpoint/protocols/invocations"
    t0 = time.perf_counter()
    rsp = httpx.post(
        url,
        params={"api-version": "v1"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": args.message},
        timeout=args.timeout,
    )
    ms = round((time.perf_counter() - t0) * 1000)
    print(f"HTTP {rsp.status_code} in {ms} ms")
    for h in ("x-ms-request-id", "apim-request-id", "x-agent-session-id"):
        if h in rsp.headers:
            print(f"{h}: {rsp.headers[h]}")
    try:
        print(json.dumps(rsp.json(), indent=2))
    except ValueError:
        print(rsp.text[:2000])
    return 0 if rsp.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
