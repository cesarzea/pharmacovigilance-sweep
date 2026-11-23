"""One-time workspace setup for the Databricks platform, idempotent: a serverless SQL warehouse and a
check that Unity Catalog is attached. Everything else (catalog, schemas, tables, views, grants) is SQL
under databricks/ applied by scripts/dbx_migrate.py.

    uv run --no-project --with databricks-sdk python -I scripts/dbx_setup.py --host https://adb-....azuredatabricks.net

Authentication is the deploying user's Azure CLI login (auth_type="azure-cli"). Prints the warehouse id and
HTTP path to put in .env (PVSWEEP_DATABRICKS_WAREHOUSE_ID, PVSWEEP_DATABRICKS_HTTP_PATH); prints no secrets.
"""

from __future__ import annotations

import argparse
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import CreateWarehouseRequestWarehouseType, EndpointInfoWarehouseType

WAREHOUSE_NAME = "pvsweep-wh"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True, help="workspace URL, https://adb-<id>.<n>.azuredatabricks.net")
    ap.add_argument("--size", default="2X-Small")
    ap.add_argument("--auto-stop-minutes", type=int, default=10)
    args = ap.parse_args()
    w = WorkspaceClient(host=args.host, auth_type="azure-cli")

    try:
        ms = w.metastores.current()
        print(f"unity catalog: metastore {ms.metastore_id} attached")
    except Exception as exc:  # noqa: BLE001 - the SDK raises a generic error when no metastore is assigned
        print(f"unity catalog: NOT attached ({type(exc).__name__}); assign a metastore to the workspace in the "
              "Databricks account console before running the migrations")

    existing = next((x for x in w.warehouses.list() if x.name == WAREHOUSE_NAME), None)
    if existing is None:
        print(f"creating serverless SQL warehouse {WAREHOUSE_NAME} ({args.size}, auto-stop {args.auto_stop_minutes} min)")
        wh = w.warehouses.create_and_wait(
            name=WAREHOUSE_NAME, cluster_size=args.size, min_num_clusters=1, max_num_clusters=1,
            auto_stop_mins=args.auto_stop_minutes, enable_serverless_compute=True,
            warehouse_type=CreateWarehouseRequestWarehouseType.PRO,
        )
    else:
        wh = w.warehouses.get(existing.id)
        print(f"warehouse {WAREHOUSE_NAME} exists ({wh.state}, type {wh.warehouse_type or EndpointInfoWarehouseType.PRO})")
    # Accounts with Default Storage have no metastore root, so a catalog created by SQL needs a managed
    # location; the workspace's own external location (default storage) is the natural place for it.
    locs = list(w.external_locations.list())
    if locs:
        print(f"PVSWEEP_DATABRICKS_MANAGED_LOCATION={locs[0].url.rstrip('/')}/pvsweep")
    print(f"PVSWEEP_DATABRICKS_WAREHOUSE_ID={wh.id}")
    print(f"PVSWEEP_DATABRICKS_HTTP_PATH={wh.odbc_params.path if wh.odbc_params else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
