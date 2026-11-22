"""Copy one sweep run from Snowflake into a local DuckDB file, so the laptop tools (evaluate, compare,
the local review app) work on it. The local file is created by LocalStore from data/stage and
data/synthetic, which gives it the same gold records and source records as Snowflake.

    python -m pvsweep_runner.snapshot --run run-xxxx --db data/local/claude-450-foundry.duckdb

Columns are copied by name; VARIANT values arrive from Snowflake as JSON text and land in DuckDB's JSON
columns unchanged. The same mapping works in the other direction for a platform migration.
"""

from __future__ import annotations

import argparse
import sys

from .env import load_dotenv
from .snowflake_store import SnowflakeStore
from .store import LocalStore

RUN_TABLES = ["SWEEP.RUN", "SWEEP.SCREENING", "SWEEP.EXTRACTION", "SWEEP.RULE_RESULT", "SWEEP.MATCH_CANDIDATE",
              "SWEEP.MATCH_DECISION", "SWEEP.FINDING", "AUDIT.MODEL_CALL"]


def copy_run(sf: SnowflakeStore, local: LocalStore, run_id: str) -> dict[str, int]:
    copied: dict[str, int] = {}
    for table in RUN_TABLES:
        cols = [r[0] for r in local.con.execute(f"DESCRIBE {table}").fetchall()]
        cur = sf._exec(f"SELECT {', '.join(cols)} FROM {table} WHERE run_id = ?", [run_id])
        try:
            rows = cur.fetchall()
        finally:
            cur.close()
        with local.lock:
            local.con.execute(f"DELETE FROM {table} WHERE run_id = ?", [run_id])
            if rows:
                local.con.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows)
        copied[table] = len(rows)
    return copied


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--db", required=True, help="local DuckDB file (created from data/stage and data/synthetic if missing)")
    ap.add_argument("--stage", default="data/stage")
    ap.add_argument("--synthetic", default="data/synthetic")
    args = ap.parse_args()
    local = LocalStore(args.db, args.stage, args.synthetic)
    sf = SnowflakeStore()
    for table, n in copy_run(sf, local, args.run).items():
        print(f"{table}: {n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
