"""Side-by-side comparison of two sweep runs (typically GPT vs Claude) on the same records.

    uv run --project runner python -I -m pvsweep_runner.compare \
        --a data/local/pvsweep-gpt.duckdb --b data/local/pvsweep-claude.duckdb [--markdown docs/ops/comparison.md]

Quality comes from pvsweep_runner.evaluate (one definition of every metric); cost and latency come
from AUDIT.MODEL_CALL. Only records present in both runs are compared.
"""

from __future__ import annotations

import argparse
import json
import sys

import duckdb

from .evaluate import extraction_scores, match_scores, screening_scores, summarise

PRICE_PER_M = {
    "gpt-5-4-mini": (0.75, 4.5), "gpt-5-5": (2.5, 15.0), "claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}


def load_run(path: str) -> tuple[str, str, dict[str, dict], dict]:
    con = duckdb.connect(path, read_only=True)
    run_id, provider = con.execute("SELECT run_id, provider FROM SWEEP.RUN ORDER BY started_at DESC LIMIT 1").fetchone()
    rows = con.execute("""
        SELECT g.record_id, g.kind, g.gold_screening, g.gold_match, g.causality_statement, g.patient_sex, g.patient_age,
               g.event_pt, g.serious, s.screening_class, e.result, e.valid, m.outcome, src.generator
        FROM EVAL.GOLD_RECORD g
        JOIN SRC.SOURCE_RECORD src ON src.record_id = g.record_id
        JOIN SWEEP.SCREENING s ON s.record_id = g.record_id AND s.run_id = ?
        LEFT JOIN SWEEP.EXTRACTION e ON e.record_id = g.record_id AND e.run_id = ?
        LEFT JOIN SWEEP.MATCH_DECISION m ON m.record_id = g.record_id AND m.run_id = ?""", [run_id, run_id, run_id]).fetchall()
    per: dict[str, dict] = {}
    for (rid, kind, g_scr, g_match, g_caus, g_sex, g_age, g_pt, g_ser, p_scr, ext, valid, m_out, generator) in rows:
        gold = {"causality_statement": g_caus, "patient_sex": g_sex, "patient_age": g_age, "event_pt": g_pt, "serious": g_ser}
        scores = screening_scores(g_scr, p_scr)
        if ext is not None:
            scores.update(extraction_scores(gold, json.loads(ext) if valid else None))
        if m_out is not None or (g_match != "NO_MATCH" and ext is not None and valid):
            scores.update(match_scores(g_match, m_out))
        per[rid] = {"record_id": rid, "kind": kind, "generator": generator.split(":")[0], "scores": scores}
    usage = con.execute("""
        SELECT step, deployment, count(*), sum(input_tokens), sum(cached_tokens), sum(output_tokens),
               avg(latency_ms), quantile_cont(latency_ms, 0.95), count_if(status <> 'ok')
        FROM AUDIT.MODEL_CALL WHERE run_id = ? GROUP BY 1, 2 ORDER BY 1""", [run_id]).fetchall()
    con.close()
    return run_id, provider, per, {"usage": usage}


def cost_of(usage) -> float:
    total = 0.0
    for step, dep, n, inp, cached, outp, *_ in usage:
        pi, po = PRICE_PER_M.get(dep, (0, 0))
        # OpenAI reports cached tokens inside prompt_tokens; Anthropic reports cache reads apart from input_tokens.
        uncached = (inp or 0) - (cached or 0) if not dep.startswith("claude") else (inp or 0)
        total += uncached / 1e6 * pi + (cached or 0) / 1e6 * pi * 0.1 + (outp or 0) / 1e6 * po
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--markdown", default=None)
    args = ap.parse_args()
    ra, pa, A, ua = load_run(args.a)
    rb, pb, B, ub = load_run(args.b)
    common = sorted(set(A) & set(B))
    lines = [f"# Provider comparison: {pa} ({ra}) vs {pb} ({rb})", "", f"{len(common)} records in both runs.", ""]

    def table(title, rows_a, rows_b):
        sa, sb = summarise(rows_a), summarise(rows_b)
        lines.append(f"## {title} ({len(rows_a)} records)")
        lines.append("")
        lines.append(f"| Metric | {pa} | {pb} |")
        lines.append("|---|---|---|")
        for k in ("screening_recall", "screening_precision", "screening_class_accuracy", "extraction_valid_share",
                  "causality_statement_accuracy", "sex_accuracy", "age_accuracy", "seriousness_accuracy", "event_hit_rate",
                  "matching_accuracy", "matching_blocked_share"):
            lines.append(f"| {k} | {sa.get(k)} | {sb.get(k)} |")
        lines.append("")

    table("All records", [A[r] for r in common], [B[r] for r in common])
    for gen in ("foundry", "anthropic"):
        ids = [r for r in common if A[r]["generator"] == gen]
        if ids:
            table(f"Records written by {gen}", [A[r] for r in ids], [B[r] for r in ids])
    kinds = sorted({A[r]["kind"] for r in common})
    lines.append("## Matching accuracy by scenario kind")
    lines.append("")
    lines.append(f"| Kind | n | {pa} | {pb} |")
    lines.append("|---|---|---|---|")
    for k in kinds:
        ids = [r for r in common if A[r]["kind"] == k]
        sa, sb = summarise([A[r] for r in ids]), summarise([B[r] for r in ids])
        lines.append(f"| {k} | {len(ids)} | {sa['matching_accuracy']} | {sb['matching_accuracy']} |")
    lines.append("")
    lines.append("## Cost and latency (audited calls)")
    lines.append("")
    lines.append("| Run | Step | Deployment | Calls | Input tok | Cached | Output tok | Latency avg ms | p95 ms | Failed |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, u in ((pa, ua["usage"]), (pb, ub["usage"])):
        for step, dep, n, inp, cached, outp, avg, p95, failed in u:
            lines.append(f"| {name} | {step} | {dep} | {n} | {inp} | {cached or 0} | {outp} | {round(avg or 0)} | {round(p95 or 0)} | {failed} |")
    lines.append("")
    lines.append(f"Estimated model cost at list prices: {pa} ${cost_of(ua['usage']):.2f}, {pb} ${cost_of(ub['usage']):.2f} "
                 "(the in-process agent's tokens are included where the framework reports them).")
    text = "\n".join(lines) + "\n"
    print(text)
    if args.markdown:
        with open(args.markdown, "w") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
