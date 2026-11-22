#!/usr/bin/env bash
# Apply snowflake/migrations/V*.sql in order, once each, recording them in OPS.MIGRATION.
# Usage: scripts/snow_migrate.sh <snow-connection-name>
set -euo pipefail
conn="${1:?snow connection name}"
cd "$(dirname "$0")/.."

applied=$(snow sql -c "$conn" -q "SELECT version FROM PVSWEEP.OPS.MIGRATION" --format JSON 2>/dev/null \
          | python3 -c 'import json,sys
try:
    rows = json.load(sys.stdin)
except Exception:
    rows = []
print("\n".join(r["VERSION"] for r in rows))' || true)

for f in snowflake/migrations/V*.sql; do
  version=$(basename "$f" | cut -d_ -f1)
  if grep -qx "$version" <<<"$applied"; then
    echo "$version already applied"
    continue
  fi
  echo "applying $f"
  snow sql -c "$conn" -f "$f" >/dev/null
  snow sql -c "$conn" -q "INSERT INTO PVSWEEP.OPS.MIGRATION (version) VALUES ('$version')" >/dev/null
done
echo "migrations up to date"
