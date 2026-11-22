"""Stage the committed synthetic data (data/synthetic) as Parquet for Snowflake."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

VENDOR_BY_CHANNEL = {"PSP": "PSPV", "MI": "MIV", "SOCIAL": "SOCV"}

GOLD_COLS = ["record_id", "kind", "timing", "gold_screening", "gold_match", "gold_outcome", "gold_day0", "substance",
             "product_name", "ownership", "reporter_type", "patient_age", "patient_sex", "event_pt", "serious", "hospitalisation",
             "causality_statement", "special_situation", "onset_date", "identifiable_patient", "identifiable_reporter",
             "anchor_case_id", "anchor_intake_id"]


def build(con: duckdb.DuckDBPyConnection, synthetic_dir: Path) -> dict:
    plan = json.loads((synthetic_dir / "plan.json").read_text())
    records = json.loads((synthetic_dir / "source_records.json").read_text()) if (synthetic_dir / "source_records.json").exists() else []
    scen = {s["record_id"]: s for s in plan["scenarios"]}

    def tmp(name: str, rows: list[dict]):
        f = synthetic_dir / f".{name}.tmp.json"
        f.write_text(json.dumps(rows, default=str))
        return f

    src_rows = [{"record_id": r["record_id"], "channel_code": r["channel"], "channel_received_date": r["channel_received_date"],
                 "country": r["country"], "vendor_code": VENDOR_BY_CHANNEL.get(r["channel"]),
                 "vendor_reference": scen[r["record_id"]]["extra_facts"].get("vendor_reference"),
                 "record_text": r["text"], "generator": r["generator"]}
                for r in records if r["text"] and r["record_id"] in scen]
    gold_rows = [{c: s.get(c) for c in GOLD_COLS} for s in plan["scenarios"]]
    files = {"source_record": src_rows, "gold_record": gold_rows, "intake_queue": plan["intake_queue"],
             "intake_log": plan["intake_log"], "vendor_tx_log": plan["vendor_tx_log"], "case_version": plan["case_version"]}
    counts = {}
    for name, rows in files.items():
        f = tmp(name, rows)
        try:
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_json_auto('{f}')")
        finally:
            f.unlink()
        counts[name] = len(rows)
    return {"rows": counts}
