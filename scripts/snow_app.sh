#!/usr/bin/env bash
# Upload the Streamlit review app to its stage and (re)create the Streamlit object.
# Usage: scripts/snow_app.sh <snow-connection-name>
set -euo pipefail
conn="${1:?snow connection name}"
cd "$(dirname "$0")/.."
snow sql -c "$conn" -q "CREATE STAGE IF NOT EXISTS PVSWEEP.OPS.APP_STAGE"
for f in snowflake/streamlit/app.py snowflake/streamlit/environment.yml; do
  snow sql -c "$conn" -q "PUT file://$(pwd)/$f @PVSWEEP.OPS.APP_STAGE/review AUTO_COMPRESS=FALSE OVERWRITE=TRUE" | tail -1
done
snow sql -c "$conn" -f snowflake/streamlit/deploy.sql
