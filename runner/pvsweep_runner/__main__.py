"""Run a sweep (steps 1-4) and print a summary against the gold labels.

    uv run --project runner python -I -m pvsweep_runner sweep --backend local \
        --account aif-pvsweep-dev-3kk4ld --provider gpt --small gpt-5-4-mini --large gpt-5-4-mini \
        --match agent --project-endpoint https://.../api/projects/proj-pvsweep-dev [--limit 40]

--provider claude-direct uses the Anthropic API with ANTHROPIC_API_KEY from .env (development only).
--match agent | baseline | hosted | none
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import blocking, matching, rules
from .providers import make_provider
from .steps import Steps
from .store import LocalStore

PRICE_PER_M = {  # USD per million tokens (input, output); used for the cost column until measured in Azure
    "gpt-5-4-mini": (0.75, 4.5), "gpt-5-5": (2.5, 15.0), "claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}
MATCH_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "matching.md"


def code_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def cmd_sweep(args) -> int:
    if args.backend == "local":
        store = LocalStore(args.db, args.stage, args.synthetic)
    else:
        from .snowflake_store import SnowflakeStore

        store = SnowflakeStore()
    small = make_provider(args.provider, args.account, args.small)
    large = make_provider(args.provider, args.account, args.large) if args.large else None
    steps = Steps(small, large, store, store.vocab())
    as_of = dt.date.fromisoformat(args.as_of)
    portfolio = {s: b for s, b in store.query("SELECT substance, brand FROM (VALUES "
                                              "('sertraline','Sertavix'),('escitalopram','Escitrel'),('duloxetine','Duloxane'),"
                                              "('venlafaxine','Venlaris')) v(substance, brand)")}
    channel_meta, ime_terms = store.channel_meta(), store.ime_terms()
    record_ids = list(args.record or [])
    if args.record_file:
        record_ids += [ln.strip() for ln in open(args.record_file) if ln.strip()]
    records = store.records(args.channels, args.limit, record_ids or None)
    run_id = store.start_run(args.provider, steps.screen_version, code_version(),
                             {"channels": args.channels, "limit": args.limit, "records": len(records), "match": args.match,
                              "as_of": args.as_of})
    print(f"{run_id}: {len(records)} records, provider {args.provider} ({args.small}{' + ' + args.large if args.large else ''}), "
          f"match={args.match}", flush=True)

    agent_runner = backend = token = None
    if args.match == "agent":
        from pvsweep_agent.backend import DuckDBBackend
        from pvsweep_agent.clients import make_client

        agent_runner = matching.AgentRunner(lambda: make_client(args.provider, args.large or args.small,
                                                                project_endpoint=args.project_endpoint, resource=args.account))
        if args.backend == "local":
            backend = DuckDBBackend(store.con)
        else:
            from pvsweep_agent.backend import SnowflakeBackend

            backend = SnowflakeBackend()
    elif args.match == "hosted":
        from azure.identity import DefaultAzureCredential

        token = DefaultAzureCredential().get_token("https://ai.azure.com/.default").token

    counts = {"screened": 0, "routed": 0, "extracted_valid": 0, "matched": 0, "blocked": 0, "invalid": 0}
    t0 = time.perf_counter()

    def work(rec):
        out = {"cls": steps.screen(run_id, rec), "valid": None, "match": None}
        if out["cls"] not in ("ADVERSE_EVENT", "SPECIAL_SITUATION"):
            return out
        out["valid"], extraction = steps.extract(run_id, rec)
        if not out["valid"]:
            return out
        report_type, vendor, fwd_days = channel_meta[rec["channel_code"]]
        rule = rules.apply(extraction, channel_report_type=report_type, is_social_odcs=rec["channel_code"] == "SOCIAL",
                           channel_received=rec["channel_received_date"], as_of=as_of, vendor_forwarding_business_days=fwd_days,
                           pv_received=None, ime_terms=ime_terms, portfolio=portfolio).as_dict()
        store.insert_rule_result(run_id, rec["record_id"], rule)
        if not extraction.get("events") and not extraction.get("special_situations"):
            return out
        patient = extraction.get("patient", {})
        terms = [e["proposed_term"] for e in extraction.get("events", [])]
        product = next((p["name_verbatim"] for p in extraction.get("products", []) if p.get("suspect", True)), None)
        cands = blocking.candidates(store, substance=rule["substance"], sex=None if patient.get("sex") == "unknown" else patient.get("sex"),
                                    age=patient.get("age_years"), terms=terms, channel_received=rec["channel_received_date"],
                                    vendor_code=rec.get("vendor_code"), vendor_reference=rec.get("vendor_reference"),
                                    product_name=product)
        store.insert_candidates(run_id, rec["record_id"], cands)
        if args.match == "none":
            return out
        payload = matching.build_payload(rec, extraction, rule, cands, [])
        if args.match == "agent":
            decision = agent_runner.match(backend, payload, f"pvsweep-matcher-{args.provider}")
            decision["tool_ids"] = []
            u = decision.get("usage") or {}
            store.insert_model_call({
                "call_id": uuid.uuid4().hex, "run_id": run_id, "record_id": rec["record_id"], "step": "match",
                "provider": args.provider, "deployment": args.large or args.small, "agent_name": f"pvsweep-matcher-{args.provider}",
                "agent_version": "in-process", "prompt_version": "matching:v1", "schema_version": "submit_match_decision:v1",
                "raw_output": json.dumps({k: v for k, v in decision.items() if k != "reply_text"}, default=str),
                "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0), "cached_tokens": 0,
                "latency_ms": decision.get("latency_ms"), "status": "ok" if decision.get("submitted") else "blocked",
            })
        elif args.match == "hosted":
            decision = matching.match_hosted(args.project_endpoint, f"pvsweep-matcher-{args.provider}", token, payload)
        else:
            decision = matching.match_baseline(large or small, MATCH_PROMPT.read_text(), payload)
            res = decision.pop("_model")
            from .steps import audit_row
            store.insert_model_call(audit_row(run_id, rec["record_id"], "match", res, "matching:v1", "baseline:v1", ""))
        ok, problems = matching.validate_decision(decision, payload)
        if not ok:
            decision["justification"] = f"REJECTED ({'; '.join(problems)}): " + str(decision.get("justification"))
            decision["outcome"] = "NO_MATCH" if decision.get("outcome") != "BLOCKED" else "BLOCKED"
        store.insert_match_decision(run_id, rec["record_id"], {**decision, "agent_name": f"pvsweep-matcher-{args.provider}",
                                                                 "agent_version": args.match, "valid": ok})
        out["match"] = decision["outcome"]
        return out

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for i, out in enumerate(pool.map(work, records), 1):
            counts["screened"] += 1
            if out["cls"] in ("ADVERSE_EVENT", "SPECIAL_SITUATION"):
                counts["routed"] += 1
                counts["extracted_valid"] += int(bool(out["valid"]))
                counts["matched"] += int(out["match"] is not None)
            elif out["cls"] == "BLOCKED":
                counts["blocked"] += 1
            elif out["cls"] == "INVALID":
                counts["invalid"] += 1
            if i % 25 == 0:
                print(f"  {i}/{len(records)}", flush=True)

    usage = store.query("SELECT deployment, sum(input_tokens), sum(output_tokens), sum(cached_tokens), count(*) "
                        "FROM AUDIT.MODEL_CALL WHERE run_id = ? GROUP BY 1", [run_id])
    cost = 0.0
    for dep, inp, outp, cached, n in usage:
        pi, po = PRICE_PER_M.get(dep, (0, 0))
        cost += ((inp or 0) - (cached or 0)) / 1e6 * pi + (cached or 0) / 1e6 * pi * 0.1 + (outp or 0) / 1e6 * po
    store.finish_run(run_id, counts, cost, "finished")
    print(f"done in {round(time.perf_counter() - t0)} s: {counts}; audited model calls {sum(u[4] for u in usage)}; "
          f"est. cost of audited calls ${cost:.2f}")
    print_eval(store, run_id)
    return 0


def print_eval(store, run_id: str):
    rows = store.query("""
        SELECT g.gold_screening, s.screening_class, count(*)
        FROM SWEEP.SCREENING s JOIN EVAL.GOLD_RECORD g USING (record_id)
        WHERE s.run_id = ? GROUP BY 1, 2 ORDER BY 1, 2""", [run_id])
    print("screening confusion (gold -> predicted):")
    for gold, pred, n in rows:
        print(f"  {gold:18} -> {pred:18} {n}")
    routed = ("ADVERSE_EVENT", "SPECIAL_SITUATION")
    tp = sum(n for g, p, n in rows if g in routed and p in routed)
    fn = sum(n for g, p, n in rows if g in routed and p not in routed)
    fp = sum(n for g, p, n in rows if g == "NO_PV_CONTENT" and p in routed)
    if tp + fn:
        print(f"routing recall {tp / (tp + fn):.3f}  (tp {tp}, fn {fn}, fp {fp})")
    ext = store.query("""
        SELECT count(*), count_if(e.valid), count_if(e.model_tier = 'large'),
               count_if(json_extract_string(e.result, '$.causality_statement.value') = g.causality_statement),
               count_if(json_extract_string(e.result, '$.patient.sex') = g.patient_sex),
               count_if(try_cast(json_extract_string(e.result, '$.patient.age_years') AS INTEGER) = g.patient_age)
        FROM SWEEP.EXTRACTION e JOIN EVAL.GOLD_RECORD g USING (record_id) WHERE e.run_id = ?""", [run_id])
    n, valid, large, caus, sex, age = ext[0]
    if n:
        print(f"extraction: {n} records, valid {valid}, escalated {large}; causality statement {caus}/{n}, sex {sex}/{n}, age {age}/{n}")
    rr = store.query("""
        SELECT count(*), count_if(r.serious = g.serious), count_if(r.ownership = g.ownership),
               count_if(r.regulatory_status IN ('overdue') = (g.timing = 'OVERDUE'))
        FROM SWEEP.RULE_RESULT r JOIN EVAL.GOLD_RECORD g USING (record_id) WHERE r.run_id = ?""", [run_id])
    if rr[0][0]:
        n, ser, own, over = rr[0]
        print(f"rules: {n} records; seriousness agrees {ser}/{n}, ownership {own}/{n}, overdue flag {over}/{n}")
    mm = store.query("""
        SELECT g.gold_match, m.outcome, count(*)
        FROM SWEEP.MATCH_DECISION m JOIN EVAL.GOLD_RECORD g USING (record_id)
        WHERE m.run_id = ? GROUP BY 1, 2 ORDER BY 1, 2""", [run_id])
    if mm:
        print("matching confusion (gold -> decided):")
        for gold, pred, n in mm:
            print(f"  {gold:26} -> {pred:26} {n}")
        agree = sum(n for g, p, n in mm if g == p)
        total = sum(n for _, _, n in mm)
        print(f"matching accuracy {agree / total:.3f} ({agree}/{total})")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sweep")
    s.add_argument("--backend", choices=["local", "snowflake"], default="local")
    s.add_argument("--db", default="data/local/pvsweep.duckdb")
    s.add_argument("--stage", default="data/stage")
    s.add_argument("--synthetic", default="data/synthetic")
    s.add_argument("--account", default=os.environ.get("PVSWEEP_FOUNDRY_ACCOUNT"), help="Foundry account name (gpt, claude)")
    s.add_argument("--project-endpoint", default=os.environ.get("PVSWEEP_PROJECT_ENDPOINT"),
                   help="Foundry project endpoint (agent and hosted matching with gpt)")
    s.add_argument("--provider", choices=["gpt", "claude", "claude-direct"], default="gpt")
    s.add_argument("--small", default=os.environ.get("PVSWEEP_GPT_SMALL"))
    s.add_argument("--large", default=os.environ.get("PVSWEEP_GPT_LARGE") or None)
    s.add_argument("--match", choices=["agent", "baseline", "hosted", "none"], default="none")
    s.add_argument("--as-of", default="2026-10-31", help="the sweep's reference date for clocks")
    s.add_argument("--channels", nargs="*", default=None)
    s.add_argument("--record", nargs="*", default=None)
    s.add_argument("--record-file", default=None, help="file with one record id per line (same records on both providers)")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    return cmd_sweep(args)


if __name__ == "__main__":
    sys.exit(main())
