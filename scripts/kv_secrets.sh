#!/usr/bin/env bash
# Store the Snowflake service-user private keys in the runner Key Vault, where the Container Apps jobs
# read them through Key Vault secret references. The keys are passed with --file, never as arguments,
# and the command output is discarded (az echoes secret values by default).
# Usage: scripts/kv_secrets.sh <key-vault-name> [secrets-dir]
set -euo pipefail
kv="${1:?usage: scripts/kv_secrets.sh <key-vault-name> [secrets-dir]}"
dir="${2:-.secrets}"
for pair in "snowflake-runner-key:snowflake_runner.p8" "snowflake-agent-key:snowflake_agent.p8"; do
  name="${pair%%:*}" file="$dir/${pair#*:}"
  [[ -f "$file" ]] || { echo "missing $file (run make snow-keys)" >&2; exit 1; }
  # The Key Vault Secrets Officer assignment from the deployment can take a few minutes to apply.
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if az keyvault secret set --vault-name "$kv" -n "$name" --file "$file" --encoding utf-8 \
         --content-type application/x-pem-file -o none --only-show-errors; then
      echo "$kv/$name set from $file"
      break
    fi
    [[ $attempt -eq 10 ]] && { echo "could not set $name in $kv" >&2; exit 1; }
    echo "retrying in 30 s (role assignment may still be propagating)" >&2
    sleep 30
  done
done
