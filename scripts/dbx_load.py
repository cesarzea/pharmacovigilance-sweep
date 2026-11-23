#!/usr/bin/env python3
"""Upload data/stage/*.parquet to the Unity Catalog volume <catalog>.ops.load_stage and COPY them into
the tables (databricks/load/load_stage.sql). Port of scripts/snow_load.sh.

Usage:
  python scripts/dbx_load.py [--stage-dir data/stage] [--var catalog=pvsweep] [--host URL] [--warehouse-id ID]
  python scripts/dbx_load.py --dry-run

Environment: PVSWEEP_DATABRICKS_HOST, PVSWEEP_DATABRICKS_WAREHOUSE_ID (or --host / --warehouse-id).
Authentication is the Azure CLI login (`az login`); no token is read or printed.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

# Load the shared helpers from scripts/dbx_migrate.py by path (python -I does not put scripts/ on sys.path).
_spec = importlib.util.spec_from_file_location("dbx_migrate", Path(__file__).resolve().with_name("dbx_migrate.py"))
dbx = importlib.util.module_from_spec(_spec)
sys.modules["dbx_migrate"] = dbx  # dataclasses look the module up while the class is created
_spec.loader.exec_module(dbx)

LOAD_SQL = dbx.DBX_DIR / "load" / "load_stage.sql"
FILES_RE = re.compile(r"FILES\s*=\s*\(\s*'([^']+)'", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    dbx.common_args(parser)
    parser.add_argument("--stage-dir", default=str(dbx.ROOT / "data" / "stage"), help="directory with the Parquet files")
    args = parser.parse_args()
    variables = dbx.parse_vars(args.var)
    catalog = variables["catalog"]
    stage_dir = Path(args.stage_dir).resolve()
    volume = f"/Volumes/{catalog}/ops/load_stage"

    local = sorted(stage_dir.glob("*.parquet"))
    statements = dbx.load_file(LOAD_SQL, variables, strict=not args.dry_run)
    needed = sorted({m for s in statements for m in FILES_RE.findall(s.sql)})
    missing = [name for name in needed if not (stage_dir / name).is_file()]
    if missing:
        raise SystemExit(f"{stage_dir} lacks {missing}; run `make stage-data` first")
    unused = sorted({p.name for p in local} - set(needed))
    if unused:
        print(f"note: uploaded but not loaded by load_stage.sql: {unused}")

    if args.dry_run:
        for p in local:
            print(f"-- upload {p.relative_to(dbx.ROOT) if p.is_relative_to(dbx.ROOT) else p} -> {volume}/{p.name} ({p.stat().st_size:,} bytes)")
        dbx.run_file(None, LOAD_SQL, variables)
        print(f"-- dry run: {len(local)} files, {len(statements)} statements, catalog {catalog}")
        return 0

    runner = dbx.connect(args)
    try:
        for p in local:
            print(f"upload {p.name} -> {volume}/{p.name} ({p.stat().st_size:,} bytes)")
            with p.open("rb") as fh:
                runner.w.files.upload(f"{volume}/{p.name}", fh, overwrite=True)
        dbx.run_file(runner, LOAD_SQL, variables)
    except dbx.StatementFailed as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    print("load finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
