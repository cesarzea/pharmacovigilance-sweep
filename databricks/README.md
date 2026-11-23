# Databricks port of the Snowflake data platform

The same schemas, tables, views and names as `snowflake/`, on Azure Databricks with Unity Catalog.
Nothing is reprocessed. Source tables load from the same Parquet files in `data/stage`. The processed
results (SWEEP, REVIEW, AUDIT) are copied from Snowflake by the sync script, which runs `COPY INTO`
against these tables.

## What maps to what

| Snowflake | Databricks |
|---|---|
| Database `PVSWEEP` | Catalog `${catalog}` (default `pvsweep`) |
| Schemas `REF`, `SRC`, `PV`, `AGENT_API`, `SWEEP`, `REVIEW`, `AUDIT`, `EVAL`, `REPORT`, `OPS` | Same schemas. Unity Catalog stores the names in lower case |
| Roles `PVSWEEP_ADMIN`, `_PIPELINE`, `_AGENT`, `_REVIEW_APP`, `_REVIEWER`, `_ANALYST`, `_CI` | Principal variables `${pvsweep_admin}` … `${pvsweep_ci}`, which default to account groups with the same names (see below) |
| `GRANT USAGE ON DATABASE` / `ON SCHEMA` | `USE CATALOG` / `USE SCHEMA` |
| `SELECT` / `INSERT` on ALL + FUTURE tables | `SELECT` / `MODIFY` on the schema, which also covers tables created later |
| `UPDATE ON SWEEP.RUN` (V008) | `MODIFY ON TABLE SWEEP.RUN`. This adds nothing, because the schema-level MODIFY already covers it |
| Nested roles (`PIPELINE`, `AGENT` granted to `CI`) | The same privileges granted to `PVSWEEP_CI` directly |
| `CREATE DATABASE ON ACCOUNT` to CI (clones) | `CREATE CATALOG ON METASTORE` to CI. A CI catalog is filled with `SHALLOW CLONE` per table |
| Ownership by `PVSWEEP_ADMIN` | Catalog, schemas, volume and views owned by the `PVSWEEP_ADMIN` group. The group also has `ALL PRIVILEGES` on the catalog |
| Stage `OPS.LOAD_STAGE`, `PUT` | Volume `ops.load_stage` at `/Volumes/<catalog>/ops/load_stage`, written with the Files API |
| `COPY INTO ... MATCH_BY_COLUMN_NAME` | `COPY INTO ... FROM (SELECT CAST(...) ...)` with `'force' = 'true'` |
| Secure views (`AGENT_API`) | Plain views. Unity Catalog views also run with the owner's rights, so the agent group needs `SELECT` on the views only. Unlike secure views, the view text is not hidden |
| Service users `PVSWEEP_RUNNER` and `PVSWEEP_AGENT` with RSA key pairs | Microsoft Entra service principals (`${runner_principal}`, `${agent_principal}`) that are members of `PVSWEEP_PIPELINE` and `PVSWEEP_AGENT`. No key material |
| Warehouse `PVSWEEP_WH` with USAGE grants | A SQL warehouse, with `CAN USE` given to each group in the workspace (not through SQL) |
| `OPS.MIGRATION` and `scripts/snow_migrate.sh` | `ops.migration` and `scripts/dbx_migrate.py` |
| NUMBER, FLOAT, TIMESTAMP_NTZ/TZ, ARRAY, VARIANT | BIGINT, DOUBLE, TIMESTAMP (a UTC instant), ARRAY<STRING>, VARIANT |

### Done outside SQL, once

1. Create the seven account groups and assign them to the workspace.
2. Add members:
   - the runner service principal to `PVSWEEP_PIPELINE`
   - the agent service principal to `PVSWEEP_AGENT`
   - reviewers to `PVSWEEP_REVIEWER`
   - the deploying engineer to `PVSWEEP_ADMIN`
3. Give every group `CAN USE` on the SQL warehouse.

The bootstrap ends by printing this checklist with both principal ids.

## Order of commands

Prerequisites:

- With the default principal variables, the account groups and memberships above exist before the bootstrap runs. Otherwise the first GRANT fails because the principal does not exist. Without groups, pass existing principals instead (see the principal variables below).
- Run `az login` as a member of `PVSWEEP_ADMIN` who holds `CREATE CATALOG` on the metastore. The bootstrap's `GRANT CREATE CATALOG ON METASTORE` also needs a metastore admin.
- Every migration also runs as a member of `PVSWEEP_ADMIN`, which owns the schemas.

Set:

- `PVSWEEP_DATABRICKS_HOST`: the workspace URL
- `PVSWEEP_DATABRICKS_WAREHOUSE_ID`

```bash
# 0. offline check: prints every statement after substitution
uv run --no-project --with databricks-sdk python -I scripts/dbx_migrate.py --dry-run --bootstrap \
  --var runner_principal=<app-id> --var agent_principal=<app-id>
uv run --no-project --with databricks-sdk python -I scripts/dbx_load.py --dry-run

# 1. catalog, schemas, volume, ownership, then V001..V009 (each recorded in ops.migration)
uv run --no-project --with databricks-sdk python -I scripts/dbx_migrate.py --bootstrap \
  --var runner_principal=<app-id> --var agent_principal=<app-id>
#    later runs apply only new migrations:
uv run --no-project --with databricks-sdk python -I scripts/dbx_migrate.py

# 2. upload data/stage/*.parquet to the volume and load (make stage-data first if data/stage is empty)
uv run --no-project --with databricks-sdk python -I scripts/dbx_load.py

# 3. the sync script copies SWEEP/REVIEW/AUDIT from Snowflake (another engineer's script)
```

Optional variables:

- `--var catalog=<name>`
- `--var managed_location_clause="MANAGED LOCATION 'abfss://<container>@<account>.dfs.core.windows.net/<path>'"`, needed when the metastore has no root storage

Principal variables. Every grantee and owner in the SQL is one of seven variables, written as `` `${...}` ``. The defaults live in `PRINCIPAL_VARS` in `scripts/dbx_migrate.py`:

| Variable | Default |
|---|---|
| `pvsweep_admin` | `PVSWEEP_ADMIN` |
| `pvsweep_pipeline` | `PVSWEEP_PIPELINE` |
| `pvsweep_agent` | `PVSWEEP_AGENT` |
| `pvsweep_review_app` | `PVSWEEP_REVIEW_APP` |
| `pvsweep_reviewer` | `PVSWEEP_REVIEWER` |
| `pvsweep_analyst` | `PVSWEEP_ANALYST` |
| `pvsweep_ci` | `PVSWEEP_CI` |

A value can be any of these, because the backticks quote names containing `@`, `.` or `-`:

- a group name
- a user e-mail
- a service principal application id

`ALTER ... OWNER TO` accepts a user as well as a group. The script refuses values that contain quotes or backslashes.

Before the account groups exist, pass one principal for all seven, for example your own user. The grants and ownership then collapse onto that user: there is no separation between the roles, and the user owns everything. To move to groups later:

1. Create the groups.
2. Re-run the bootstrap with the defaults. It transfers ownership.
3. Re-apply the grants. V004 is already recorded in `ops.migration`, so either run its statements by hand or delete its row and run the migration again; every grant is idempotent.
4. Revoke the user's direct grants.

Statements that may fail with "already exists" are marked `-- @ignore-error <ERROR_CLASS>`. The only ones are V009's `ADD COLUMNS`, because Databricks has no `ADD COLUMN IF NOT EXISTS`.

## VARIANT

The Snowflake VARIANT columns use the Databricks `VARIANT` type, which needs a current SQL warehouse or DBR 15.3+. On a warehouse without VARIANT support:

- Change every VARIANT column in V006 and V009 to `STRING` (JSON text).
- Drop V009's `SET TBLPROPERTIES ('delta.feature.variantType-preview' ...)` statement.

Code that reads JSON must use `col:path` and `col:path::string`, which work on both VARIANT and a JSON STRING column. No view in V005 or V007 reads JSON.

JSON text loaded into a VARIANT column needs `parse_json(col)` in the `COPY INTO ... FROM (SELECT ...)`.

## Append-only gap

Snowflake run-time roles have INSERT but not UPDATE or DELETE on SWEEP, REVIEW and AUDIT. Unity Catalog has no insert-only privilege: `MODIFY` is insert, update and delete together. These grants therefore do not enforce append-only.

The enforcing option is `ALTER TABLE ... SET TBLPROPERTIES ('delta.appendOnly' = 'true')` on the SWEEP (except RUN), REVIEW and AUDIT tables. It is not set here, because it also blocks `TRUNCATE` and `DELETE` for the owner, so the Snowflake sync could not re-copy into those tables. Set it once the sync is final.

## Verified offline, and not

Verified on 2026-11-22 with local Spark 4.0.1 and Delta 4.0.0 against the real `data/stage` files:

- All the SQL in bootstrap, V001–V009 and `load_stage.sql` that open-source Spark can run ran in session time zones UTC and Europe/Madrid.
  - Translated: `COPY INTO` became `INSERT ... SELECT` from the file, and `TRUNCATE` became `DELETE`.
  - Stripped: the `CONSTRAINT ... PRIMARY KEY` clauses and schema comments.
  - Skipped: 95 Unity Catalog-only statements (grants, ownership, catalog, volume).
- The load ran twice, and the row counts matched the manifest both times.
- Timestamps: the DuckDB microsecond `TIMESTAMP` columns read as `TIMESTAMP_NTZ` with the right values. Unlike Snowflake, there is no nanosecond misreading.
  - A plain cast to `TIMESTAMP` shifts by the session time zone.
  - The load therefore appends `'Z'`, and the final query prints UTC min/max for checking. Expected: intake log 2024-11-11 16:05 to 2026-10-22 16:05, the same as Snowflake.
- The null-typed Parquet columns (`intake_queue.vendor_reference`, `case_id`) are readable and load as NULL.
- `REPORT.RECONCILIATION_SUMMARY` gives the same numbers as Snowflake, and `AGENT_API.SAFETY_CASE_SUMMARY` gives the same arrays.
- V009 re-runs cleanly: the error class is `FIELD_ALREADY_EXISTS`, and adding a VARIANT column needs the variant table feature set first.

Not verified, because it needs a workspace:

- table ownership: tables stay owned by whoever ran the migration, and only the catalog, schemas, volume and views are given to `PVSWEEP_ADMIN`
- Unity Catalog grants, ownership transfers and volume statements
- `COPY INTO` syntax and `force` behaviour
- `CREATE CATALOG` without a managed location
- the `col:path` syntax
- informational primary keys
- the `variantType-preview` feature name on the target warehouse
- the Files API upload
- the Statement Execution API polling
