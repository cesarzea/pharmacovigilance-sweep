"""Stage the public datasets as Parquet files ready for Snowflake.

    uv run --with-requirements runner/requirements-load.txt python -I -m pvsweep_load \
        --out data/stage --reference-date 2026-10-31 --brands config/brands.json

Writes one Parquet file per target table plus data_source.parquet (the manifest for REF.DATA_SOURCE).
The Snowflake side (`make snow-load`) PUTs these files to a stage and COPYs them into the tables.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import duckdb

from . import faers, synthetic, vaers, vocab

TABLES = {
    "safety_case": "PV.SAFETY_CASE",
    "case_drug": "PV.CASE_DRUG",
    "case_event": "PV.CASE_EVENT",
    "case_indication": "PV.CASE_INDICATION",
    "vaers_coding": "EVAL.VAERS_CODING",
    "vaers_outcomes": "EVAL.VAERS_OUTCOMES",
    "pt_vocab": "REF.PT_VOCAB",
    "source_record": "SRC.SOURCE_RECORD",
    "gold_record": "EVAL.GOLD_RECORD",
    "intake_queue": "PV.INTAKE_QUEUE",
    "intake_log": "PV.INTAKE_LOG",
    "vendor_tx_log": "PV.VENDOR_TX_LOG",
    "case_version": "PV.CASE_VERSION",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/stage"))
    ap.add_argument("--reference-date", default="2026-10-31", help="newest FAERS receipt date is shifted onto this date")
    ap.add_argument("--brands", type=Path, default=Path("config/brands.json"))
    ap.add_argument("--vaers-sample", type=int, default=400)
    ap.add_argument("--cache", type=Path, default=Path("data/cache"), help="downloaded source files (kept between runs)")
    ap.add_argument("--synthetic", type=Path, default=Path("data/synthetic"))
    ap.add_argument("--push-snowflake", action="store_true", help="after staging, PUT and COPY into Snowflake (runner key pair)")
    args = ap.parse_args()

    brands = json.loads(args.brands.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    manifest = []
    print("FAERS: reading EU/EEA reports for the portfolio substances", flush=True)
    m = faers.build(con, args.reference_date, brands, args.cache)
    manifest.append(m)
    print(f"  date offset {m['date_offset_days']} days, rows {m['rows']}", flush=True)
    print("VAERS: sampling benchmarks", flush=True)
    for m in vaers.build(con, args.vaers_sample, args.cache):
        manifest.append(m)
        print(f"  rows {m['rows']}", flush=True)
    print("vocabulary", flush=True)
    manifest.append(vocab.build(con, args.cache))
    print("synthetic records", flush=True)
    m = synthetic.build(con, args.synthetic)
    manifest.append(m)
    print(f"  rows {m['rows']}", flush=True)

    for table in TABLES:
        con.execute(f"COPY {table} TO '{args.out / table}.parquet' (FORMAT PARQUET)")

    loaded_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows = []
    for m in manifest:
        src = m.get("source")
        for table, n in m["rows"].items():
            rows.append({
                "target_table": TABLES[table],
                "dataset": src.repo if src else "derived",
                "revision": src.revision if src else None,
                "licence": src.licence if src else None,
                "attribution": src.attribution if src else ("synthetic (scenario-first, model-rendered)" if table in
                                                            ("source_record", "gold_record", "intake_queue", "intake_log",
                                                             "vendor_tx_log", "case_version") else "derived from the sources above"),
                "row_count": n,
                "date_offset_days": m.get("date_offset_days"),
                "reference_date": args.reference_date if m.get("date_offset_days") is not None else None,
                "loaded_at": loaded_at,
            })
    manifest_path = args.out / "manifest.json"
    manifest_path.write_text(json.dumps(rows, indent=2))
    con.execute(f"CREATE OR REPLACE TABLE data_source AS SELECT * FROM read_json_auto('{manifest_path}')")
    con.execute(f"COPY data_source TO '{args.out / 'data_source'}.parquet' (FORMAT PARQUET)")
    print(f"staged {len(TABLES) + 1} files in {args.out}")
    if args.push_snowflake:
        from .push import push

        print("pushing to Snowflake", flush=True)
        push(args.out, Path(__file__).resolve().parents[2] / "snowflake" / "load" / "load_stage.sql")
    return 0


if __name__ == "__main__":
    sys.exit(main())
