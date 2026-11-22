#!/usr/bin/env bash
# Run the review app locally over a DuckDB file (default: data/local/pvsweep.duckdb).
set -euo pipefail
cd "$(dirname "$0")/.."
export PVSWEEP_LOCAL_DB="${PVSWEEP_LOCAL_DB:-data/local/pvsweep.duckdb}"
exec uv run -q --project runner --with streamlit --with pandas streamlit run snowflake/streamlit/app.py \
  --server.port "${PORT:-8501}" --server.headless true --browser.gatherUsageStats false
