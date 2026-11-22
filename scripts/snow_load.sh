#!/usr/bin/env bash
# PUT the staged Parquet files to OPS.LOAD_STAGE and COPY them into the tables.
# Usage: scripts/snow_load.sh <snow-connection-name> [stage-dir]
set -euo pipefail
conn="${1:?snow connection name}"
dir="${2:-data/stage}"
cd "$(dirname "$0")/.."

for f in "$dir"/*.parquet; do
  snow sql -c "$conn" -q "PUT file://$(pwd)/$f @PVSWEEP.OPS.LOAD_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE" | tail -1
done
snow sql -c "$conn" -f snowflake/load/load_stage.sql
