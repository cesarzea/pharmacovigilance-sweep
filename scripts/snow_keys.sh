#!/usr/bin/env bash
# Generate RSA key pairs for the Snowflake service users. Private keys are written to a local,
# git-ignored directory only; the deploy step moves them to Key Vault and a Foundry connection.
# Usage: scripts/snow_keys.sh [out-dir]
set -euo pipefail
out="${1:-.secrets}"
mkdir -p "$out"
for name in runner agent; do
  if [[ -f "$out/snowflake_$name.p8" ]]; then
    echo "$out/snowflake_$name.p8 exists, keeping it"
  else
    openssl genrsa 2048 2>/dev/null | openssl pkcs8 -topk8 -inform PEM -out "$out/snowflake_$name.p8" -nocrypt
    chmod 600 "$out/snowflake_$name.p8"
  fi
  openssl rsa -in "$out/snowflake_$name.p8" -pubout -out "$out/snowflake_$name.pub" 2>/dev/null
  # PEM body without header/footer lines, as Snowflake's RSA_PUBLIC_KEY expects
  grep -v -- '-----' "$out/snowflake_$name.pub" | tr -d '\n' > "$out/snowflake_$name.pub.body"
  echo "$name: $out/snowflake_$name.p8 (private), $out/snowflake_$name.pub.body (public key body)"
done
