# Databricks platform

The POC runs on two data platforms with the same tables: Snowflake (the original) and Azure Databricks
with Unity Catalog. This page is the operating guide for the Databricks side; each section is owned by
the script it describes.

## Why two platforms

The pipeline only needs a SQL store with semi-structured columns, so the same schema is kept on both
platforms to show that the sweep, the review app and the reports are not tied to one vendor. Snowflake is
where the sweeps have been run; Databricks receives the same data without re-running the models, which
would cost model calls and give slightly different results.

## What is loaded and what is copied

| Data | Tables | How it reaches Databricks |
| --- | --- | --- |
| Sources, reference data, gold records | `src`, `ref`, `pv`, `eval` schemas | Loaded from the Parquet files in `data/stage/`, the same files Snowflake loads (`scripts/dbx_load.py`) |
| Sweep results | `sweep.run`, `screening`, `extraction`, `rule_result`, `match_candidate`, `match_decision`, `finding` | Copied from Snowflake (`scripts/dbx_sync.py`) |
| Model call audit | `audit.model_call` | Copied from Snowflake |
| Reviewer work | every table in `review` (`decision`, `case_intake_package`, `compliance_finding`, `follow_up`) | Copied from Snowflake |

Nothing is reprocessed: the copied rows are the ones Snowflake holds, with the same run ids, finding ids
and timestamps.

## Command order

1. Deploy the workspace (Bicep, `deployDatabricks=true`), then `scripts/dbx_setup.py` for the serverless
   SQL warehouse; put the printed `PVSWEEP_DATABRICKS_WAREHOUSE_ID` and `PVSWEEP_DATABRICKS_HTTP_PATH` in
   `.env`.
2. Bootstrap and migrations: catalog, schemas, tables, the `ops.load_stage` volume and grants from the SQL
   under `databricks/`.
3. Load the stage: `scripts/dbx_load.py` uploads `data/stage/*.parquet` and runs `COPY INTO`.
4. Sync the results from Snowflake (below).
5. The review app.

### Sync the results from Snowflake

```bash
python -I scripts/dbx_sync.py export                       # all runs; or --run <run_id>, --tables RUN,FINDING
uv run --no-project --with databricks-sdk python -I scripts/dbx_sync.py import --dry-run   # print only
uv run --no-project --with databricks-sdk python -I scripts/dbx_sync.py import            # upload + COPY INTO
```

`export` needs only the Snowflake CLI connection (default `pvsweep`, role `PVSWEEP_ADMIN`; override with
`--conn` or `SNOW_CONN`). For each table it unloads a `SELECT` to
`@PVSWEEP.OPS.LOAD_STAGE/export/<table>/` as Parquet, downloads it with `snow stage copy` into
`data/export/<table>/` (git-ignored), removes the stage files and writes `data/export/manifest.json`
(scope, run ids, row counts, files, column types and encodings). Each export replaces the previous
contents of `data/export/`. It reads the tables and never writes to them.

`import` uploads each table's files to `/Volumes/<catalog>/ops/load_stage/sync/<table>/<export_id>/` with
the Databricks SDK and runs, through the SQL Statement Execution API on the warehouse:

```sql
COPY INTO <catalog>.<schema>.<table>
FROM (SELECT <column casts> FROM '/Volumes/<catalog>/ops/load_stage/sync/<table>/<export_id>/')
FILEFORMAT = PARQUET
```

The casts come from `DESCRIBE TABLE` on the target, so the target schema decides the types.

- Re-running the same import is a no-op: `COPY INTO` skips files it has already loaded.
- `--replace` deletes the rows being reloaded first and loads with `'force' = 'true'`: rows of the
  exported run ids for the run-scoped tables; for `review`, the rows of the run's findings when the export
  was for one run, or the whole table (`TRUNCATE`) when it was for all runs. Use it after rows changed in
  Snowflake, for example new review decisions.
- `--force` reloads already loaded files without deleting, which duplicates rows; it exists for a target
  that was emptied by hand.
- An export for all runs plus `--replace` mirrors every run Snowflake has; runs that exist only in
  Databricks are left alone.

## Environment

| Variable | Used by | Meaning |
| --- | --- | --- |
| `PVSWEEP_DATABRICKS_HOST` | import (or `--host`) | Workspace URL, `https://adb-<id>.<n>.azuredatabricks.net` |
| `PVSWEEP_DATABRICKS_WAREHOUSE_ID` | import | SQL warehouse that runs the statements |
| `PVSWEEP_DATABRICKS_HTTP_PATH` | runner, app | Warehouse HTTP path for the SQL connector |
| `PVSWEEP_DATABRICKS_CATALOG` | import (or `--catalog`) | Unity Catalog catalog, default `pvsweep` |
| `SNOW_CONN` | export (or `--conn`) | Snowflake CLI connection, default `pvsweep` |

The scripts read these from the environment or `.env`. Databricks authentication is the user's Azure
CLI login (`az login`, `auth_type="azure-cli"`); no token is stored. The user needs `WRITE VOLUME` on
`ops.load_stage`, `MODIFY` and `SELECT` on the target tables and `CAN USE` on the warehouse.

## Limitations

- **Semi-structured columns.** Snowflake `VARIANT` columns travel as JSON text (`TO_JSON`) and are
  restored with `parse_json(...)` when the Databricks column is `VARIANT`; when it is `STRING` the JSON
  text is stored as is. `parse_json` re-serializes, so key order and number formatting may differ from
  the Snowflake rendering while the values are equal.
- **Timestamps.** Snowflake writes `TIMESTAMP_NTZ` to Parquet as UTC-adjusted milliseconds, so the export
  sends them as text (`YYYY-MM-DD HH24:MI:SS.FF6`) and the import casts them as
  `CAST(concat(col, 'Z') AS TIMESTAMP)`, a UTC instant independent of the session time zone (the
  Databricks tables use `TIMESTAMP`).
- **Numbers.** Integer `NUMBER` columns arrive as `DECIMAL(38,0)` and are cast to the target type.
- **Run filter on review tables.** `review` has no run id; a one-run export selects review rows through
  `sweep.finding`, and `--replace` deletes through the target's `sweep.finding`, so `sweep.finding` must
  be imported in the same or an earlier import (the script imports `sweep` and `audit` before `review`).
- **Identities.** The sync runs as the signed-in user. Running it unattended needs a Databricks service
  principal (an Entra ID managed identity added to the workspace) with the grants above, and a Snowflake
  key-pair user with read access to `REVIEW`, which the runner's `PVSWEEP_PIPELINE` role does not have.

## Reverse direction (Databricks to Snowflake)

The manifest format does not depend on the direction, so the reverse sync is the same two phases with the
platforms swapped:

1. Export: per table, `INSERT OVERWRITE DIRECTORY '/Volumes/<catalog>/ops/load_stage/sync_out/<table>/'
   USING PARQUET SELECT ...` with `to_json(<variant>)` and timestamps formatted as text, then download
   the files with `w.files.download` and write the same `manifest.json`.
2. Import: `PUT` the files to `@PVSWEEP.OPS.LOAD_STAGE/sync/<table>/` and `COPY INTO PVSWEEP.<schema>.<table>`
   with a transforming `SELECT` that applies `PARSE_JSON($1:<col>)` to JSON columns and
   `$1:<col>::TIMESTAMP_NTZ` to timestamps, run as `PVSWEEP_ADMIN` because the run-time roles have no
   `DELETE` on these schemas.

Not implemented yet; the functions in `scripts/dbx_sync.py` are split by platform to make it an addition
rather than a rewrite.

## Identities without a person

`scripts/dbx_principals.py --runner <client id> --agent <client id> ...` registers the runner's managed
identity and the hosted agents' identities as workspace service principals with the `workspace-access`
and `databricks-sql-access` entitlements, applies the Unity Catalog grants of their role (pipeline or
agent) and gives them `CAN USE` on the warehouse. All three are needed: Unity Catalog grants alone leave
the SQL endpoints refusing the principal. The hosted agents are deployed for this platform with
`make deploy-agents PLATFORM=databricks` (one agent version per switch); `make deploy-agents` puts them
back on Snowflake.
