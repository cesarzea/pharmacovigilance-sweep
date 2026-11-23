"""Copy already processed results (SWEEP, AUDIT, REVIEW) from Snowflake to Databricks without reprocessing.

Two phases, run in order; the files in data/export/ are the hand-off between them:

    # 1. Snowflake -> data/export/ (Snowflake CLI, read-only on the tables; writes only to the internal stage)
    python -I scripts/dbx_sync.py export [--run RUN_ID] [--tables RUN,FINDING] [--conn pvsweep]

    # 2. data/export/ -> Unity Catalog volume -> COPY INTO the Delta tables
    uv run --no-project --with databricks-sdk python -I scripts/dbx_sync.py import \
        [--host https://adb-....azuredatabricks.net] [--catalog pvsweep] [--replace] [--force] \
        [--json-as-string] [--tables ...] [--dry-run]

Export: for each table, `COPY INTO @PVSWEEP.OPS.LOAD_STAGE/export/<table>/` unloads a SELECT to Parquet and
`snow stage copy` downloads the files to data/export/<table>/. VARIANT columns are unloaded as JSON text
(TO_JSON) and TIMESTAMP columns as ISO text with microseconds, so the Parquet carries plain strings that
are cast to the target type on the Databricks side (Snowflake writes TIMESTAMP_NTZ to Parquet as
UTC-adjusted milliseconds, which is neither NTZ nor lossless). A TIMESTAMP target gets
CAST(concat(col, 'Z') AS TIMESTAMP), a UTC instant whatever the session time zone. data/export/manifest.json records the scope,
row counts, files, column encodings and the run ids exported. The Snowflake CLI connection is used for
every table because the runner's role (PVSWEEP_PIPELINE) has no grant on REVIEW.

Import: uploads each table's files to /Volumes/<catalog>/ops/load_stage/sync/<table>/<export_id>/ with the
Databricks SDK and runs `COPY INTO <catalog>.<schema>.<table> FROM (SELECT <casts> FROM '<dir>')
FILEFORMAT = PARQUET` through the SQL Statement Execution API. Casts follow `DESCRIBE TABLE` of the target:
JSON text becomes parse_json(...) when the target column is VARIANT and stays a string otherwise.
COPY INTO skips files it already loaded, so re-running an import is a no-op; `--replace` first deletes the
exported runs' rows (run-scoped tables) or the REVIEW rows in scope and reloads with force. `--dry-run`
prints the statements without connecting (types are inferred from the manifest).

Authentication: Snowflake CLI connection (default `pvsweep`); Databricks: the user's Azure CLI login
(auth_type="azure-cli"). Environment: PVSWEEP_DATABRICKS_HOST, PVSWEEP_DATABRICKS_WAREHOUSE_ID, optional
PVSWEEP_DATABRICKS_CATALOG (default pvsweep); read from the process environment or .env. No secrets are
printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = ROOT / "data" / "export"
MANIFEST = "manifest.json"
SF_DATABASE = "PVSWEEP"
SF_STAGE = "@PVSWEEP.OPS.LOAD_STAGE/export"

# Order matters for import: REVIEW deletes in run scope look up the run's findings in the target.
RUN_SCOPED = [
    ("SWEEP", "RUN"), ("SWEEP", "SCREENING"), ("SWEEP", "EXTRACTION"), ("SWEEP", "RULE_RESULT"),
    ("SWEEP", "MATCH_CANDIDATE"), ("SWEEP", "MATCH_DECISION"), ("SWEEP", "FINDING"), ("AUDIT", "MODEL_CALL"),
]
REVIEW_SCHEMA = "REVIEW"  # every table in it, discovered at export time; scoped by FINDING_ID

JSON_TYPES = {"VARIANT", "OBJECT", "ARRAY"}
TS_FORMAT = "YYYY-MM-DD HH24:MI:SS.FF6"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---- Snowflake side ------------------------------------------------------------------------------------

def snow_json(conn: str, sql: str) -> list[dict]:
    out = subprocess.run(["snow", "sql", "-c", conn, "--format", "JSON", "-q", sql],
                         capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise SystemExit(f"snow sql failed:\n{sql}\n{out.stderr.strip() or out.stdout.strip()}")
    return json.loads(out.stdout or "[]")


def sf_columns(conn: str, schemas: list[str]) -> dict[tuple[str, str], list[dict]]:
    rows = snow_json(conn, (
        "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, NUMERIC_SCALE, ORDINAL_POSITION "
        f"FROM {SF_DATABASE}.INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA IN "
        f"({', '.join(repr(s) for s in schemas)}) ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"))
    cols: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        cols.setdefault((r["TABLE_SCHEMA"], r["TABLE_NAME"]), []).append(
            {"name": r["COLUMN_NAME"], "sf_type": r["DATA_TYPE"], "scale": r["NUMERIC_SCALE"]})
    return cols


def encoding(sf_type: str) -> str | None:
    if sf_type in JSON_TYPES:
        return "json"
    if sf_type.startswith("TIMESTAMP"):
        return "timestamp_text"
    return None


def select_expr(col: dict) -> str:
    name = col["name"]
    enc = encoding(col["sf_type"])
    if enc == "json":
        return f"TO_JSON({name}) AS {name}"
    if enc == "timestamp_text":
        return f"TO_VARCHAR({name}, '{TS_FORMAT}') AS {name}"
    return name


def scope_filter(schema: str, run_id: str | None) -> str:
    if not run_id:
        return ""
    if schema == REVIEW_SCHEMA:
        return f" WHERE FINDING_ID IN (SELECT FINDING_ID FROM {SF_DATABASE}.SWEEP.FINDING WHERE RUN_ID = '{run_id}')"
    return f" WHERE RUN_ID = '{run_id}'"


def export(args) -> int:
    if args.run and not RUN_ID_RE.match(args.run):
        raise SystemExit(f"invalid run id: {args.run!r}")
    conn = args.conn
    cols = sf_columns(conn, ["SWEEP", "AUDIT", REVIEW_SCHEMA])
    tables = [t for t in RUN_SCOPED if t in cols]
    tables += sorted(k for k in cols if k[0] == REVIEW_SCHEMA)
    missing = [t for t in RUN_SCOPED if t not in cols]
    if missing:
        raise SystemExit(f"source tables missing in Snowflake: {missing}")
    tables = filter_tables(tables, args.tables)

    export_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_ids = [r["RUN_ID"] for r in snow_json(
        conn, f"SELECT RUN_ID FROM {SF_DATABASE}.SWEEP.RUN{scope_filter('SWEEP', args.run)} ORDER BY RUN_ID")]
    if args.run and not run_ids:
        raise SystemExit(f"run {args.run} not found in {SF_DATABASE}.SWEEP.RUN")

    if EXPORT_DIR.exists():  # one export at a time: the manifest describes exactly what is on disk
        shutil.rmtree(EXPORT_DIR)
    EXPORT_DIR.mkdir(parents=True)
    manifest = {"format": 1, "direction": "snowflake->databricks", "export_id": export_id,
                "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": {"platform": "snowflake", "database": SF_DATABASE},
                "scope": {"run_id": args.run, "run_ids": run_ids}, "tables": {}}
    print(f"export {export_id}: scope {'run ' + args.run if args.run else 'all runs'} ({len(run_ids)} runs)")
    total_rows = total_bytes = 0
    for schema, table in tables:
        tcols = cols[(schema, table)]
        fq = f"{SF_DATABASE}.{schema}.{table}"
        where = scope_filter(schema, args.run)
        stage_dir = f"{SF_STAGE}/{table.lower()}/"
        local_dir = EXPORT_DIR / table.lower()
        local_dir.mkdir(parents=True)

        expected = int(snow_json(conn, f"SELECT COUNT(*) AS N FROM {fq}{where}")[0]["N"])
        snow_json(conn, f"REMOVE {stage_dir}")
        files: list[dict] = []
        unloaded = 0
        if expected:
            res = snow_json(conn, (
                f"COPY INTO {stage_dir} FROM (SELECT {', '.join(select_expr(c) for c in tcols)} FROM {fq}{where}) "
                "FILE_FORMAT = (TYPE = PARQUET) HEADER = TRUE OVERWRITE = TRUE"))
            unloaded = sum(int(r.get("rows_unloaded", 0)) for r in res)
            cp = subprocess.run(["snow", "stage", "copy", "-c", conn, stage_dir, str(local_dir), "--overwrite",
                                 "--recursive"], capture_output=True, text=True, check=False)
            if cp.returncode != 0:
                raise SystemExit(f"snow stage copy failed for {table}:\n{cp.stderr.strip() or cp.stdout.strip()}")
            snow_json(conn, f"REMOVE {stage_dir}")
            for f in sorted(local_dir.rglob("*.parquet")):
                files.append({"path": f.relative_to(local_dir).as_posix(), "bytes": f.stat().st_size})
        if unloaded != expected:
            raise SystemExit(f"{fq}: unloaded {unloaded} rows, expected {expected}")
        nbytes = sum(f["bytes"] for f in files)
        total_rows += expected
        total_bytes += nbytes
        manifest["tables"][table] = {
            "schema": schema, "table": table, "scope": "review" if schema == REVIEW_SCHEMA else "run",
            "rows": expected, "bytes": nbytes, "files": files,
            "columns": [{"name": c["name"], "sf_type": c["sf_type"], "scale": c["scale"],
                         "encoding": encoding(c["sf_type"])} for c in tcols]}
        print(f"  {schema}.{table:<22} {expected:>7} rows  {len(files):>2} files  {nbytes / 1024:>9.1f} KiB")
    (EXPORT_DIR / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"total: {total_rows} rows, {total_bytes / 1024:.1f} KiB in {EXPORT_DIR.relative_to(ROOT)}/")
    return 0


# ---- Databricks side -----------------------------------------------------------------------------------

def default_target_type(col: dict, json_as_string: bool) -> str:
    t = col["sf_type"]
    if t in JSON_TYPES:
        return "STRING" if json_as_string else "VARIANT"
    if t.startswith("TIMESTAMP"):
        return "TIMESTAMP"
    if t == "NUMBER":
        return "BIGINT" if (col.get("scale") or 0) == 0 else "DECIMAL(38,9)"
    return {"TEXT": "STRING", "FLOAT": "DOUBLE", "BOOLEAN": "BOOLEAN", "DATE": "DATE"}.get(t, "STRING")


def cast_expr(col: dict, target_type: str) -> str:
    src = f"`{col['name']}`"
    tt = target_type.upper()
    if col["encoding"] == "json":
        return f"parse_json({src})" if tt == "VARIANT" else src
    if col["encoding"] == "timestamp_text" and tt == "TIMESTAMP":
        # Snowflake NTZ values are UTC wall clock; the 'Z' makes the cast independent of the session time zone.
        return f"CAST(concat({src}, 'Z') AS TIMESTAMP)"
    if tt == "STRING":
        return src
    return f"CAST({src} AS {target_type})"


def copy_statement(spec: dict, target: str, volume_dir: str, target_types: dict[str, tuple[str, str]],
                   force: bool) -> str:
    exprs = []
    for col in spec["columns"]:
        key = col["name"].lower()
        if key not in target_types:
            raise SystemExit(f"{target}: column {col['name']} not in target table")
        tname, ttype = target_types[key]
        exprs.append(f"{cast_expr(col, ttype)} AS `{tname}`")
    opts = " COPY_OPTIONS ('force' = 'true')" if force else ""
    return f"COPY INTO {target} FROM (SELECT {', '.join(exprs)} FROM '{volume_dir}') FILEFORMAT = PARQUET{opts}"


def replace_statement(spec: dict, target: str, catalog: str, scope: dict) -> str:
    run_ids = scope["run_ids"]
    if spec["scope"] == "run":
        if not run_ids:
            return ""
        return f"DELETE FROM {target} WHERE run_id IN ({', '.join(sql_str(r) for r in run_ids)})"
    if scope["run_id"]:
        return (f"DELETE FROM {target} WHERE finding_id IN (SELECT finding_id FROM {catalog}.sweep.finding "
                f"WHERE run_id = {sql_str(scope['run_id'])})")
    return f"TRUNCATE TABLE {target}"


def sql_str(v: str) -> str:
    if not RUN_ID_RE.match(v):
        raise SystemExit(f"unexpected identifier value: {v!r}")
    return f"'{v}'"


class Dbx:
    def __init__(self, host: str, warehouse_id: str):
        from databricks.sdk import WorkspaceClient

        self.w = WorkspaceClient(host=host, auth_type="azure-cli")
        self.warehouse_id = warehouse_id

    def sql(self, statement: str):
        from databricks.sdk.service.sql import StatementState

        r = self.w.statement_execution.execute_statement(statement=statement, warehouse_id=self.warehouse_id,
                                                         wait_timeout="50s")
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            r = self.w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            err = r.status.error.message if r.status.error else r.status.state
            raise SystemExit(f"statement failed: {err}\n{statement}")
        cols = [c.name for c in (r.manifest.schema.columns or [])] if r.manifest and r.manifest.schema else []
        rows = r.result.data_array if r.result and r.result.data_array else []
        return [dict(zip(cols, row)) for row in rows]

    def describe(self, target: str) -> dict[str, tuple[str, str]]:
        out = {}
        for r in self.sql(f"DESCRIBE TABLE {target}"):
            name = r.get("col_name") or ""
            if not name or name.startswith("#"):
                break  # partition / detail sections follow the column list
            out[name.lower()] = (name, r["data_type"])
        return out

    def upload(self, local: Path, remote: str):
        with local.open("rb") as fh:
            self.w.files.upload(remote, fh, overwrite=True)


def import_(args) -> int:
    manifest_path = EXPORT_DIR / MANIFEST
    if not manifest_path.exists():
        raise SystemExit(f"{manifest_path.relative_to(ROOT)} not found: run `export` first")
    manifest = json.loads(manifest_path.read_text())
    catalog = args.catalog or env("PVSWEEP_DATABRICKS_CATALOG") or "pvsweep"
    if not IDENT_RE.match(catalog):
        raise SystemExit(f"invalid catalog name: {catalog!r}")
    export_id = manifest["export_id"]
    scope = manifest["scope"]
    names = [k for k in manifest["tables"]]
    order = {t: i for i, (_, t) in enumerate(RUN_SCOPED)}
    names.sort(key=lambda t: (order.get(t, len(order)), t))
    names = [t for t in names if t in {x[1] for x in filter_tables([("", n) for n in names], args.tables)}]

    dbx = None
    if not args.dry_run:
        host = args.host or env("PVSWEEP_DATABRICKS_HOST")
        warehouse = env("PVSWEEP_DATABRICKS_WAREHOUSE_ID")
        if not host or not warehouse:
            raise SystemExit("set PVSWEEP_DATABRICKS_HOST (or --host) and PVSWEEP_DATABRICKS_WAREHOUSE_ID")
        dbx = Dbx(host, warehouse)

    print(f"import {export_id} into {catalog} ({'run ' + scope['run_id'] if scope['run_id'] else 'all runs'}"
          f"{', replace' if args.replace else ''}{', dry run' if args.dry_run else ''})")
    force = args.force or args.replace
    for name in names:
        spec = manifest["tables"][name]
        target = f"{catalog}.{spec['schema'].lower()}.{spec['table'].lower()}"
        volume_dir = f"/Volumes/{catalog}/ops/load_stage/sync/{spec['table'].lower()}/{export_id}/"
        if dbx:
            target_types = dbx.describe(target)
        else:
            target_types = {c["name"].lower(): (c["name"].lower(), default_target_type(c, args.json_as_string))
                            for c in spec["columns"]}
        print(f"-- {target}: {spec['rows']} rows, {len(spec['files'])} files")
        if args.replace:
            stmt = replace_statement(spec, target, catalog, scope)
            if stmt:
                print(stmt + ";")
                if dbx:
                    dbx.sql(stmt)
        if not spec["files"]:
            continue
        for f in spec["files"]:
            remote = volume_dir + f["path"]
            print(f"-- upload data/export/{spec['table'].lower()}/{f['path']} -> {remote}")
            if dbx:
                dbx.upload(EXPORT_DIR / spec["table"].lower() / f["path"], remote)
        stmt = copy_statement(spec, target, volume_dir, target_types, force)
        print(stmt + ";")
        if dbx:
            res = dbx.sql(stmt)
            print(f"   {res[0] if res else 'done'}")
    return 0


# ---- shared --------------------------------------------------------------------------------------------

def filter_tables(tables: list[tuple[str, str]], wanted: str | None) -> list[tuple[str, str]]:
    if not wanted:
        return tables
    want = {w.strip().upper().split(".")[-1] for w in wanted.split(",") if w.strip()}
    unknown = want - {t for _, t in tables}
    if unknown:
        raise SystemExit(f"unknown tables: {sorted(unknown)}; known: {sorted(t for _, t in tables)}")
    return [x for x in tables if x[1] in want]


def env(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == name:
                return v.strip().strip('"').strip("'") or None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="phase", required=True)
    ex = sub.add_parser("export", help="Snowflake -> data/export/ (Parquet + manifest.json)")
    ex.add_argument("--conn", default=os.environ.get("SNOW_CONN", "pvsweep"), help="Snowflake CLI connection name")
    ex.add_argument("--run", help="export one run (default: all runs)")
    ex.add_argument("--tables", help="comma-separated subset, e.g. RUN,FINDING,DECISION")
    im = sub.add_parser("import", help="data/export/ -> Databricks volume -> COPY INTO")
    im.add_argument("--host", help="workspace URL (default: PVSWEEP_DATABRICKS_HOST)")
    im.add_argument("--catalog", help="Unity Catalog catalog (default: PVSWEEP_DATABRICKS_CATALOG or pvsweep)")
    im.add_argument("--tables", help="comma-separated subset of the exported tables")
    im.add_argument("--replace", action="store_true",
                    help="delete the exported runs' rows (REVIEW: rows in scope, or truncate) and reload with force")
    im.add_argument("--force", action="store_true", help="reload files COPY INTO has already loaded")
    im.add_argument("--json-as-string", action="store_true",
                    help="dry run only: assume JSON columns are STRING in the target (real runs use DESCRIBE TABLE)")
    im.add_argument("--dry-run", action="store_true", help="print the uploads and statements; connect to nothing")
    args = ap.parse_args()
    return export(args) if args.phase == "export" else import_(args)


if __name__ == "__main__":
    sys.exit(main())
