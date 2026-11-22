#!/usr/bin/env bash
# Start one execution of the sweep Container Apps job with overridden arguments, wait for it to finish
# and print its console logs from Log Analytics. Core az CLI only (az resource / az rest).
#
# Usage: scripts/run_sweep_job.sh <resource-group> <job-name> <log-analytics-workspace-guid> -- <sweep args...>
# The arguments replace the job's default args (they are appended after the provider and deployment
# options, so they win). Without --limit the script refuses to start, unless ALLOW_FULL_SWEEP=1.
set -euo pipefail
rg="${1:?resource group}" job="${2:?job name}" ws="${3:?Log Analytics workspace id}"
shift 3
[[ "${1:-}" == "--" ]] && shift
args=("$@")
if [[ " ${args[*]} " != *" --limit "* && "${ALLOW_FULL_SWEEP:-0}" != "1" ]]; then
  echo "refusing to start a sweep without --limit (set ALLOW_FULL_SWEEP=1 to run the whole corpus)" >&2
  exit 2
fi
api="2024-03-01"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

job_id="$(az resource show -g "$rg" -n "$job" --resource-type Microsoft.App/jobs --api-version "$api" --query id -o tsv)"
# The start body is the job's own template (image, env, secret references) with only the args replaced.
az resource show --ids "$job_id" --api-version "$api" --query properties.template -o json > "$tmp/template.json"
python3 -I - "$tmp/template.json" "${args[@]}" > "$tmp/start.json" <<'PY'
import json, sys
t = json.load(open(sys.argv[1]))
c = t["containers"][0]
c["args"] = sys.argv[2:]
print(json.dumps({"containers": [c], "initContainers": t.get("initContainers") or []}))
PY

execution="$(az rest --method post --url "https://management.azure.com${job_id}/start?api-version=${api}" \
  --body @"$tmp/start.json" --query name -o tsv)"
echo "started $execution with args: ${args[*]}"

exec_url="https://management.azure.com${job_id}/executions/${execution}?api-version=${api}"
# Check that the override reached the execution; stop it at once if it did not.
applied="$(az rest --method get --url "$exec_url" --query "properties.template.containers[0].args" -o tsv | tr '\n\t' '  ')"
if [[ " $applied " != *" --limit "* && "${ALLOW_FULL_SWEEP:-0}" != "1" ]]; then
  echo "execution args were not overridden ($applied); stopping $execution" >&2
  az rest --method post --url "https://management.azure.com${job_id}/executions/${execution}/stop?api-version=${api}" -o none || true
  exit 3
fi

start=$(date +%s)
status=""
while :; do
  status="$(az rest --method get --url "$exec_url" --query properties.status -o tsv)"
  case "$status" in
    Succeeded|Failed|Stopped|Degraded) break ;;
  esac
  sleep 20
done
echo "$execution: $status after $(( $(date +%s) - start )) s (polling time; see startTime/endTime below)"
az rest --method get --url "$exec_url" --query "properties.{status:status,startTime:startTime,endTime:endTime}" -o table

# Console logs reach Log Analytics a few minutes after the replica ends.
query="ContainerAppConsoleLogs_CL | where ContainerGroupName_s startswith '${execution}' | order by TimeGenerated asc | project TimeGenerated, Log_s"
python3 -I -c 'import json,sys; print(json.dumps({"query": sys.argv[1], "timespan": "P1D"}))' "$query" > "$tmp/query.json"
for attempt in $(seq 1 20); do
  rows="$(az rest --method post --url "https://api.loganalytics.io/v1/workspaces/${ws}/query" \
    --resource https://api.loganalytics.io --body @"$tmp/query.json" \
    --query "tables[0].rows" -o json)"
  if [[ "$rows" != "[]" ]]; then
    printf '%s' "$rows" | python3 -I -c 'import json,sys; [print(r[0], r[1]) for r in json.load(sys.stdin)]'
    break
  fi
  [[ $attempt -eq 20 ]] && echo "no console logs in Log Analytics yet; query again later: $query" >&2
  sleep 30
done
[[ "$status" == "Succeeded" ]]
