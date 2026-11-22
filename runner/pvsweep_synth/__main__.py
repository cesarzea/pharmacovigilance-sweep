"""Generate the synthetic channel records (ground truth first, text second).

    uv run --project runner python -I -m pvsweep_synth plan   --out data/synthetic [--seed 7 --total 450]
    uv run --project runner python -I -m pvsweep_synth render --out data/synthetic --account <foundry> --deployment gpt-5-4-mini

`plan` is deterministic and free. `render` calls the model once per record (plus retries) and writes
source_records.json with the text, the model used and the validator result. Both outputs are
committed, so every deployment loads the same data.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

from . import plan as planner
from . import render as R


def cmd_plan(args) -> int:
    brands = json.loads(Path(args.brands).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    p = planner.build(args.seed, args.total, args.stage, brands, dt.date.fromisoformat(args.reference_date))
    (out / "plan.json").write_text(json.dumps(p, indent=1, ensure_ascii=False, default=str))
    from collections import Counter
    kinds = Counter(s["kind"] for s in p["scenarios"])
    chans = Counter(s["channel"] for s in p["scenarios"])
    print(f"{len(p['scenarios'])} scenarios; intake_queue {len(p['intake_queue'])}, intake_log {len(p['intake_log'])}, "
          f"vendor_tx_log {len(p['vendor_tx_log'])}, case_version {len(p['case_version'])}")
    print("by channel:", dict(chans))
    print("by kind:", dict(kinds))
    return 0


async def render_all(args) -> int:
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AsyncOpenAI

    brands = json.loads(Path(args.brands).read_text())
    out = Path(args.out)
    p = json.loads((out / "plan.json").read_text())
    done_path = out / "source_records.json"
    done = {r["record_id"]: r for r in json.loads(done_path.read_text())} if done_path.exists() else {}

    def scenario_hash(s: dict) -> str:
        return hashlib.sha256(json.dumps(s, sort_keys=True, default=str).encode()).hexdigest()[:16]

    # A rendered text is only valid for the exact scenario it was written for.
    stale = [rid for rid, r in done.items() if r.get("scenario_hash") != scenario_hash(next((x for x in p["scenarios"] if x["record_id"] == rid), {}))]
    for rid in stale:
        del done[rid]
    if stale:
        print(f"{len(stale)} rendered records no longer match their scenario and will be re-rendered", flush=True)

    sem = asyncio.Semaphore(args.concurrency)
    if args.generator == "claude":
        from anthropic import AsyncAnthropic
        from pvsweep_runner.env import load_dotenv

        load_dotenv()
        aclient = AsyncAnthropic()
        generator_label = f"anthropic:{args.deployment}"

        async def generate(prompt: str):
            msg = await aclient.messages.create(model=args.deployment, max_tokens=600, system=R.SYSTEM,
                                                messages=[{"role": "user", "content": prompt}])
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            return text, {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens,
                          "total_tokens": msg.usage.input_tokens + msg.usage.output_tokens}
    else:
        token = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")
        client = AsyncOpenAI(base_url=f"https://{args.account}.services.ai.azure.com/openai/v1/", api_key=token())
        generator_label = f"foundry:{args.deployment}"

        async def generate(prompt: str):
            rsp = await client.responses.create(model=args.deployment, instructions=R.SYSTEM, input=prompt)
            return rsp.output_text, (rsp.usage.model_dump(exclude_none=True) if rsp.usage else None)

    async def one(s: dict) -> dict:
        complaint = None
        last_error = ""
        attempts = []
        for attempt in range(1, 4):
            async with sem:
                t0 = time.perf_counter()
                for backoff in (5, 15, 30, 60, 90):
                    try:
                        text, usage = await generate(R.user_prompt(s, brands, complaint))
                        break
                    except Exception as exc:  # noqa: BLE001 - rate limits, connection errors, 5xx
                        status = getattr(exc, "status_code", None)
                        if status is not None and 400 <= status < 500 and status != 429:
                            raise
                        last_error = f"{type(exc).__name__}"
                        await asyncio.sleep(backoff)
                else:
                    raise RuntimeError(f"gave up after five attempts: {last_error}")
                ms = round((time.perf_counter() - t0) * 1000)
            text = text.strip()
            problems = R.validate(text, s, brands)
            attempts.append({"attempt": attempt, "latency_ms": ms, "problems": problems, "usage": usage})
            if not problems:
                break
            complaint = "; ".join(problems)
        return {"record_id": s["record_id"], "scenario_hash": scenario_hash(s), "channel": s["channel"],
                "channel_received_date": s["channel_received_date"],
                "country": s["country"], "text": text, "generator": generator_label,
                "validated": not problems, "validator_problems": problems, "attempts": attempts}

    todo = [s for s in p["scenarios"] if s["record_id"] not in done or args.redo]
    if args.share:
        # deterministic split of the catalogue between generators: "1/2" renders the odd positions
        k, n = (int(x) for x in args.share.split("/"))
        todo = [s for i, s in enumerate(p["scenarios"]) if i % n == k - 1 and (s["record_id"] not in done or args.redo)]
    if args.kinds:
        todo = [s for s in todo if s["kind"] in args.kinds]
    if args.limit:
        todo = todo[: args.limit]
    print(f"rendering {len(todo)} records with {args.deployment} (concurrency {args.concurrency})", flush=True)

    def save():
        ordered_now = [done[s["record_id"]] for s in p["scenarios"] if s["record_id"] in done]
        done_path.write_text(json.dumps(ordered_now, indent=1, ensure_ascii=False))

    async def guarded(s):
        try:
            return await one(s)
        except Exception as exc:  # noqa: BLE001 - keep going, record the failure
            return {"record_id": s["record_id"], "scenario_hash": scenario_hash(s), "channel": s["channel"],
                    "channel_received_date": s["channel_received_date"],
                    "country": s["country"], "text": "", "generator": generator_label, "validated": False,
                    "validator_problems": [f"render failed: {type(exc).__name__}: {exc}"], "attempts": []}

    results = []
    for i, coro in enumerate(asyncio.as_completed([guarded(s) for s in todo]), 1):
        r = await coro
        results.append(r)
        done[r["record_id"]] = r
        if i % 25 == 0 or i == len(todo):
            save()
            print(f"  {i}/{len(todo)}", flush=True)
    ordered = [done[s["record_id"]] for s in p["scenarios"] if s["record_id"] in done]
    ok = sum(1 for r in ordered if r["validated"])
    tokens = sum((a["usage"] or {}).get("total_tokens", 0) for r in results for a in r["attempts"])
    print(f"generators: {dict(__import__('collections').Counter(r['generator'] for r in ordered))}")
    print(f"{ok}/{len(ordered)} validated; {len(ordered) - ok} kept with validator problems; {tokens} tokens this run")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--out", default="data/synthetic")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--total", type=int, default=450)
    p.add_argument("--stage", default="data/stage")
    p.add_argument("--brands", default="config/brands.json")
    p.add_argument("--reference-date", default="2026-10-31")
    r = sub.add_parser("render")
    r.add_argument("--out", default="data/synthetic")
    r.add_argument("--brands", default="config/brands.json")
    r.add_argument("--generator", choices=["gpt", "claude"], default="gpt")
    r.add_argument("--account", default=None, help="Foundry account (gpt generator)")
    r.add_argument("--deployment", default="gpt-5-4-mini", help="Foundry deployment or Anthropic model id")
    r.add_argument("--share", default=None, help="k/n: render only every n-th scenario starting at k (split between generators)")
    r.add_argument("--concurrency", type=int, default=6)
    r.add_argument("--redo", action="store_true")
    r.add_argument("--limit", type=int, default=0, help="render only the first N pending records (smoke test)")
    r.add_argument("--kinds", nargs="*", default=None, help="render only these scenario kinds (with --redo to replace)")
    args = ap.parse_args()
    if args.cmd == "plan":
        return cmd_plan(args)
    return asyncio.run(render_all(args))


if __name__ == "__main__":
    sys.exit(main())
