"""Register the Azure identities that reach Databricks without a person (the runner identity and the
hosted agents' identities) as workspace service principals and grant them what their role needs.
Idempotent; run after the migrations.

    uv run --no-project --with databricks-sdk python -I scripts/dbx_principals.py \
        --runner <runner identity client id> --agent <hosted agent identity client id> [--agent ...]

Grants mirror databricks/migrations/V004__grants.sql for PVSWEEP_PIPELINE (runner) and PVSWEEP_AGENT
(agents); in a team setup the principals join the account groups instead and this script is not needed.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

PIPELINE_GRANTS = [
    "GRANT USE CATALOG ON CATALOG {c} TO `{p}`",
    *[f"GRANT USE SCHEMA ON SCHEMA {{c}}.{s} TO `{{p}}`" for s in ("ref", "src", "pv", "agent_api", "sweep", "audit", "eval", "ops")],
    *[f"GRANT SELECT ON SCHEMA {{c}}.{s} TO `{{p}}`" for s in ("ref", "src", "pv", "agent_api", "eval")],
    *[f"GRANT SELECT, MODIFY ON SCHEMA {{c}}.{s} TO `{{p}}`" for s in ("sweep", "audit", "eval")],
    "GRANT READ VOLUME, WRITE VOLUME ON VOLUME {c}.ops.load_stage TO `{p}`",
]
AGENT_GRANTS = [
    "GRANT USE CATALOG ON CATALOG {c} TO `{p}`",
    "GRANT USE SCHEMA ON SCHEMA {c}.agent_api TO `{p}`",
    "GRANT SELECT ON SCHEMA {c}.agent_api TO `{p}`",
]


ENTITLEMENTS = ["workspace-access", "databricks-sql-access"]  # without the SQL one the Statement/SQL endpoints answer "API disabled"


def ensure_service_principal(w: WorkspaceClient, app_id: str, name: str) -> None:
    from databricks.sdk.service.iam import ComplexValue

    entitlements = [ComplexValue(value=e) for e in ENTITLEMENTS]
    existing = next(iter(w.service_principals.list(filter=f'applicationId eq "{app_id}"')), None)
    if existing is None:
        w.service_principals.create(application_id=app_id, display_name=name, active=True, entitlements=entitlements)
        print(f"{name}: service principal {app_id} added to the workspace with {ENTITLEMENTS}")
        return
    have = {e.value for e in (existing.entitlements or [])}
    if not set(ENTITLEMENTS) <= have:
        w.service_principals.update(id=existing.id, application_id=app_id, display_name=existing.display_name or name,
                                    active=True, entitlements=entitlements)
        print(f"{name}: service principal {app_id} updated with {ENTITLEMENTS}")
    else:
        print(f"{name}: service principal {app_id} already in the workspace with the entitlements")


def grant_warehouse_use(w: WorkspaceClient, warehouse: str, app_id: str) -> None:
    """CAN USE on the SQL warehouse is a workspace permission, not a Unity Catalog grant."""
    from databricks.sdk.service.sql import WarehouseAccessControlRequest, WarehousePermissionLevel

    w.warehouses.update_permissions(warehouse, access_control_list=[
        WarehouseAccessControlRequest(service_principal_name=app_id, permission_level=WarehousePermissionLevel.CAN_USE)])


def run_sql(w: WorkspaceClient, warehouse: str, sql: str) -> None:
    r = w.statement_execution.execute_statement(warehouse_id=warehouse, statement=sql, wait_timeout="50s")
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status and r.status.state != StatementState.SUCCEEDED:
        raise SystemExit(f"failed: {sql}\n{r.status.error.message if r.status.error else r.status.state}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("PVSWEEP_DATABRICKS_HOST"))
    ap.add_argument("--warehouse-id", default=os.environ.get("PVSWEEP_DATABRICKS_WAREHOUSE_ID"))
    ap.add_argument("--catalog", default=os.environ.get("PVSWEEP_DATABRICKS_CATALOG", "pvsweep"))
    ap.add_argument("--runner", help="application (client) id of the runner's user-assigned identity")
    ap.add_argument("--agent", action="append", default=[], help="application id of a hosted agent identity; repeatable")
    args = ap.parse_args()
    w = WorkspaceClient(host=args.host, auth_type="azure-cli")
    for app_id, name, grants in ([(args.runner, "pvsweep-runner", PIPELINE_GRANTS)] if args.runner else []) + \
            [(a, f"pvsweep-agent-{i + 1}", AGENT_GRANTS) for i, a in enumerate(args.agent)]:
        ensure_service_principal(w, app_id, name)
        for g in grants:
            run_sql(w, args.warehouse_id, g.format(c=args.catalog, p=app_id))
        grant_warehouse_use(w, args.warehouse_id, app_id)
        print(f"{name}: {len(grants)} grants applied, CAN USE on warehouse {args.warehouse_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
