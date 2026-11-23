"""Create or update the Databricks App pvsweep-review (the review app in databricks/app/) and deploy it, idempotent.

    uv run --no-project --with databricks-sdk python -I scripts/dbx_app.py [--dry-run] [--source-path /Workspace/...]

Steps: upload databricks/app/{app.py,app.yaml,requirements.txt} to the workspace files path; create the app with the
SQL warehouse as a resource (key `sql-warehouse`, CAN_USE: app.yaml reads its id with `valueFrom: sql-warehouse`), or
update its resources if it exists; start its compute if stopped; deploy the uploaded source (SNAPSHOT); print the
app URL, its service principal and the Unity Catalog grants that principal needs (printed, not executed, unless
--apply-grants is given: they run on the same warehouse as the deploying user, who must own or manage the catalog).

Authentication is the deploying user's Azure CLI login (auth_type="azure-cli"). Environment: PVSWEEP_DATABRICKS_HOST,
PVSWEEP_DATABRICKS_WAREHOUSE_ID, optional PVSWEEP_DATABRICKS_CATALOG (default pvsweep) and
PVSWEEP_DATABRICKS_APP_PATH (workspace folder for the source, default /Workspace/Users/<deploying user>/apps/pvsweep-review,
not Shared, which every workspace user can write); read from the
process environment or .env. --dry-run contacts nothing (no Azure CLI token, no workspace call) and prints the plan.
No secrets are printed.

SDK calls (databricks-sdk, verified against https://databricks-sdk-py.readthedocs.io/en/latest/workspace/apps/apps.html
and the installed package): w.apps.get / create_and_wait(App) / update(name, App) / start_and_wait(name) /
deploy_and_wait(name, AppDeployment); w.workspace.mkdirs / upload(path, content, format=ImportFormat.AUTO, overwrite).
App resources and app.yaml: https://docs.databricks.com/aws/en/dev-tools/databricks-apps/app-runtime and
https://docs.databricks.com/aws/en/dev-tools/databricks-apps/sql-warehouse
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "databricks" / "app"
APP_FILES = ["app.py", "app.yaml", "requirements.txt"]
APP_NAME = "pvsweep-review"
APP_DESCRIPTION = "Pharmacovigilance Sweep: reviewer queue, decisions and case intake packages"
WAREHOUSE_RESOURCE = "sql-warehouse"   # must match `valueFrom` in databricks/app/app.yaml
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# What the app reads and writes. SWEEP.FINDING also receives an INSERT on the legacy path (runs swept before the
# findings step, local development only): MODIFY on SWEEP is deliberately not granted.
READ_SCHEMAS = ["src", "sweep", "report"]
WRITE_SCHEMAS = ["review"]


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


def grants(catalog: str, principal: str) -> list[str]:
    """Unity Catalog privileges for the app's service principal, addressed by its application (client) id."""
    p = f"`{principal}`"
    out = [f"GRANT USE CATALOG ON CATALOG {catalog} TO {p}"]
    for s in READ_SCHEMAS:
        out.append(f"GRANT USE SCHEMA, SELECT ON SCHEMA {catalog}.{s} TO {p}")
    for s in WRITE_SCHEMAS:
        out.append(f"GRANT USE SCHEMA, SELECT, MODIFY ON SCHEMA {catalog}.{s} TO {p}")
    return out


def desired_resources(warehouse_id: str):
    from databricks.sdk.service.apps import (AppResource, AppResourceSqlWarehouse,
                                             AppResourceSqlWarehouseSqlWarehousePermission)

    return [AppResource(name=WAREHOUSE_RESOURCE, description="SQL warehouse for the review app",
                        sql_warehouse=AppResourceSqlWarehouse(
                            id=warehouse_id, permission=AppResourceSqlWarehouseSqlWarehousePermission.CAN_USE))]


def same_resources(current, wanted) -> bool:
    def key(rs):
        return sorted((r.name, r.sql_warehouse.id if r.sql_warehouse else None,
                       r.sql_warehouse.permission.value if r.sql_warehouse and r.sql_warehouse.permission else None)
                      for r in rs or [])
    return key(current) == key(wanted)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the plan; contact neither Azure nor the workspace")
    ap.add_argument("--source-path", default=None, help="workspace folder for the app source")
    ap.add_argument("--apply-grants", action="store_true", help="run the Unity Catalog grants instead of printing them")
    ap.add_argument("--no-deploy", action="store_true", help="create/update the app and upload, but do not deploy")
    args = ap.parse_args()

    host = env("PVSWEEP_DATABRICKS_HOST")
    warehouse_id = env("PVSWEEP_DATABRICKS_WAREHOUSE_ID")
    catalog = env("PVSWEEP_DATABRICKS_CATALOG") or "pvsweep"
    source_path = (args.source_path or env("PVSWEEP_DATABRICKS_APP_PATH") or "").rstrip("/") or None
    missing = [n for n, v in (("PVSWEEP_DATABRICKS_HOST", host), ("PVSWEEP_DATABRICKS_WAREHOUSE_ID", warehouse_id)) if not v]
    if missing:
        raise SystemExit(f"missing environment: {', '.join(missing)}")
    if not IDENT_RE.match(catalog):
        raise SystemExit(f"invalid catalog name: {catalog!r}")
    for f in APP_FILES:
        if not (APP_DIR / f).is_file():
            raise SystemExit(f"missing app file: {APP_DIR / f}")

    from databricks.sdk.service.apps import App, AppDeployment, AppDeploymentMode, ComputeState

    resources = desired_resources(warehouse_id)

    if args.dry_run:
        source_path = source_path or f"/Workspace/Users/<deploying user>/apps/{APP_NAME}"
        deployment = AppDeployment(source_code_path=source_path, mode=AppDeploymentMode.SNAPSHOT)
        print(f"[dry-run] workspace {host} (auth_type=azure-cli), catalog {catalog}")
        print(f"[dry-run] mkdirs {source_path}")
        for f in APP_FILES:
            print(f"[dry-run] upload {(APP_DIR / f).relative_to(ROOT)} -> {source_path}/{f} "
                  f"({(APP_DIR / f).stat().st_size} bytes, overwrite)")
        print(f"[dry-run] apps.get({APP_NAME!r}); if absent apps.create_and_wait("
              f"{App(name=APP_NAME, description=APP_DESCRIPTION, resources=resources).as_dict()})")
        print("[dry-run]   else apps.update with the same resources if they differ; start_and_wait if compute is stopped")
        if not args.no_deploy:
            print(f"[dry-run] apps.deploy_and_wait({APP_NAME!r}, {deployment.as_dict()})")
        print("[dry-run] Unity Catalog grants for the app's service principal (application id known after create):")
        for g in grants(catalog, "<service_principal_client_id>"):
            print(f"  {g};")
        return 0

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import NotFound
    from databricks.sdk.service.workspace import ImportFormat

    w = WorkspaceClient(host=host, auth_type="azure-cli")
    source_path = source_path or f"/Workspace/Users/{w.current_user.me().user_name}/apps/{APP_NAME}"
    deployment = AppDeployment(source_code_path=source_path, mode=AppDeploymentMode.SNAPSHOT)

    print(f"source path {source_path}")
    w.workspace.mkdirs(source_path)
    for f in APP_FILES:
        # AUTO keeps a .py without the notebook header as a workspace file (not a notebook); yaml/txt are files.
        w.workspace.upload(f"{source_path}/{f}", (APP_DIR / f).read_bytes(), format=ImportFormat.AUTO, overwrite=True)
        print(f"uploaded {source_path}/{f}")

    try:
        app = w.apps.get(APP_NAME)
        print(f"app {APP_NAME} exists (compute {app.compute_status.state if app.compute_status else 'unknown'})")
        if not same_resources(app.resources, resources):
            app = w.apps.update(APP_NAME, App(name=APP_NAME, description=APP_DESCRIPTION, resources=resources))
            print(f"updated resources: {WAREHOUSE_RESOURCE} -> warehouse {warehouse_id} (CAN_USE)")
    except NotFound:
        print(f"creating app {APP_NAME} (this starts its compute)")
        app = w.apps.create_and_wait(App(name=APP_NAME, description=APP_DESCRIPTION, resources=resources))

    state = app.compute_status.state if app.compute_status else None
    if state in (ComputeState.STOPPED, ComputeState.ERROR, None):
        print(f"starting compute ({state})")
        app = w.apps.start_and_wait(APP_NAME)

    if not args.no_deploy:
        d = w.apps.deploy_and_wait(APP_NAME, deployment)
        print(f"deployment {d.deployment_id}: {d.status.state if d.status else 'unknown'} "
              f"{(d.status.message if d.status else '') or ''}")

    app = w.apps.get(APP_NAME)
    principal = app.service_principal_client_id
    print(f"app URL: {app.url}")
    print(f"service principal: {app.service_principal_name} (application id {principal})")
    statements = grants(catalog, principal)
    if args.apply_grants:
        from databricks.sdk.service.sql import StatementState

        for s in statements:
            r = w.statement_execution.execute_statement(s, warehouse_id, wait_timeout="50s")
            state = r.status.state if r.status else None
            print(f"{s}: {state}")
            if state != StatementState.SUCCEEDED:
                err = r.status.error.message if r.status and r.status.error else ""
                raise SystemExit(f"grant failed: {err}")
    else:
        print("Run as the catalog owner (or rerun with --apply-grants):")
        for s in statements:
            print(f"  {s};")
    return 0


if __name__ == "__main__":
    sys.exit(main())
