"""Model-quality metrics against the gold labels, per run, and the export used by Foundry evaluations.

    uv run --project runner python -I -m pvsweep_runner.evaluate --run <run_id> [--export data/eval/run.jsonl]

Every metric has one definition here; Foundry's custom evaluators (foundry/evaluators/*.py) apply the
same functions row by row.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROUTED = ("ADVERSE_EVENT", "SPECIAL_SITUATION")


def screening_scores(gold: str, predicted: str) -> dict:
    g, p = gold in ROUTED, predicted in ROUTED
    return {"routed_tp": int(g and p), "routed_fn": int(g and not p), "routed_fp": int(not g and p),
            "class_exact": int(gold == predicted)}


def extraction_scores(gold: dict, ext: dict | None) -> dict:
    if not ext:
        return {"valid": 0, "causality": 0, "sex": 0, "age": 0, "serious": 0, "event_hit": 0}
    patient = ext.get("patient", {})
    s = ext.get("seriousness", {})
    serious = any(s.get(k) for k in s) or any(e.get("hospitalisation") for e in ext.get("events", []))
    terms = {e.get("proposed_term", "").strip().lower() for e in ext.get("events", [])}
    verbatims = " ".join(e.get("verbatim", "") for e in ext.get("events", [])).lower()
    gold_pt = (gold.get("event_pt") or "").lower()
    event_hit = int(bool(gold_pt) and (gold_pt in terms or gold_pt.split()[0] in verbatims))
    return {
        "valid": 1,
        "causality": int(ext.get("causality_statement", {}).get("value") == gold.get("causality_statement")),
        "sex": int(patient.get("sex") == (gold.get("patient_sex") or "unknown")),
        "age": int(gold.get("patient_age") is not None and patient.get("age_years") is not None
                   and abs(float(patient["age_years"]) - float(gold["patient_age"])) < 0.6),
        "serious": int(bool(serious) == bool(gold.get("serious"))),
        "event_hit": event_hit,
    }


def match_scores(gold: str, decided: str | None) -> dict:
    return {"match_exact": int(decided == gold), "match_blocked": int(decided in (None, "BLOCKED"))}


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    s = {k: sum(r["scores"].get(k, 0) for r in rows) for k in
         ("routed_tp", "routed_fn", "routed_fp", "class_exact", "valid", "causality", "sex", "age", "serious", "event_hit",
          "match_exact", "match_blocked")}
    routed_gold = s["routed_tp"] + s["routed_fn"]
    extracted = sum(1 for r in rows if "valid" in r["scores"])
    matched = sum(1 for r in rows if "match_exact" in r["scores"])
    return {
        "records": n,
        "screening_recall": round(s["routed_tp"] / routed_gold, 3) if routed_gold else None,
        "screening_precision": round(s["routed_tp"] / (s["routed_tp"] + s["routed_fp"]), 3) if s["routed_tp"] + s["routed_fp"] else None,
        "screening_class_accuracy": round(s["class_exact"] / n, 3) if n else None,
        "extraction_valid_share": round(s["valid"] / extracted, 3) if extracted else None,
        "causality_statement_accuracy": round(s["causality"] / s["valid"], 3) if s["valid"] else None,
        "sex_accuracy": round(s["sex"] / s["valid"], 3) if s["valid"] else None,
        "age_accuracy": round(s["age"] / s["valid"], 3) if s["valid"] else None,
        "seriousness_accuracy": round(s["serious"] / s["valid"], 3) if s["valid"] else None,
        "event_hit_rate": round(s["event_hit"] / s["valid"], 3) if s["valid"] else None,
        "matching_accuracy": round(s["match_exact"] / matched, 3) if matched else None,
        "matching_blocked_share": round(s["match_blocked"] / matched, 3) if matched else None,
    }


def rows_for_run(store, run_id: str) -> list[dict]:
    recs = store.query("""
        SELECT g.record_id, g.kind, g.gold_screening, g.gold_match, g.gold_outcome, g.causality_statement, g.patient_sex,
               g.patient_age, g.event_pt, g.serious, s.screening_class, e.result, e.valid, m.outcome
        FROM EVAL.GOLD_RECORD g
        JOIN SWEEP.SCREENING s ON s.record_id = g.record_id AND s.run_id = ?
        LEFT JOIN SWEEP.EXTRACTION e ON e.record_id = g.record_id AND e.run_id = ?
        LEFT JOIN SWEEP.MATCH_DECISION m ON m.record_id = g.record_id AND m.run_id = ?""", [run_id, run_id, run_id])
    out = []
    for r in recs:
        (rid, kind, g_scr, g_match, g_out, g_caus, g_sex, g_age, g_pt, g_ser, p_scr, ext_json, ext_valid, m_out) = r
        gold = {"causality_statement": g_caus, "patient_sex": g_sex, "patient_age": g_age, "event_pt": g_pt, "serious": g_ser}
        scores = screening_scores(g_scr, p_scr)
        if ext_json is not None:
            ext = json.loads(ext_json) if isinstance(ext_json, str) else ext_json
            scores.update(extraction_scores(gold, ext if ext_valid else None))
        if m_out is not None or g_match != "NO_MATCH" and ext_json is not None and ext_valid:
            scores.update(match_scores(g_match, m_out))
        out.append({"record_id": rid, "kind": kind, "gold": {"screening": g_scr, "match": g_match, "outcome": g_out, **gold},
                    "predicted": {"screening": p_scr, "match": m_out}, "scores": scores})
    return out


def main() -> int:
    from .store import LocalStore

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/local/pvsweep.duckdb")
    ap.add_argument("--stage", default="data/stage")
    ap.add_argument("--synthetic", default="data/synthetic")
    ap.add_argument("--run", default=None, help="run id; default: the latest")
    ap.add_argument("--export", default=None, help="write per-record rows as JSONL for Foundry evaluations")
    args = ap.parse_args()
    store = LocalStore(args.db, args.stage, args.synthetic)
    run_id = args.run or store.query("SELECT run_id FROM SWEEP.RUN ORDER BY started_at DESC LIMIT 1")[0][0]
    rows = rows_for_run(store, run_id)
    summary = summarise(rows)
    print(json.dumps({"run_id": run_id, **summary}, indent=2))
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
    print("by scenario kind (screening recall / matching accuracy):")
    for kind, rs in sorted(by_kind.items()):
        s = summarise(rs)
        print(f"  {kind:28} n={len(rs):3}  screening={s['screening_recall']}  match={s['matching_accuracy']}")
    if args.export:
        Path(args.export).parent.mkdir(parents=True, exist_ok=True)
        with open(args.export, "w") as f:
            for r in rows:
                # flat rows: Foundry wraps each line as `item` for the evaluators
                f.write(json.dumps({"run_id": run_id, "record_id": r["record_id"], "kind": r["kind"],
                                    "gold_screening": r["gold"]["screening"], "predicted_screening": r["predicted"]["screening"],
                                    "gold_match": r["gold"]["match"], "predicted_match": r["predicted"]["match"],
                                    "gold_causality": r["gold"]["causality_statement"],
                                    "scores": r["scores"]}, default=str) + "\n")
        print(f"exported {len(rows)} rows to {args.export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
