# Runner job: the sweep as an Azure Container Apps job

The sweep (`python -m pvsweep_runner sweep --backend snowflake`) runs unattended as the manual-trigger
Container Apps job `job-pvsweep-<env>-sweep`. Every resource comes from `infra/` through the Makefile;
nothing is created by hand.

## What gets deployed (`make deploy DEPLOY_RUNNER=1`)

`infra/modules/runner.bicep`, in the resource group:

- Log Analytics workspace `log-pvsweep-<env>` (30-day retention) and App Insights `appi-pvsweep-<env>`.
- Key Vault `kv-pvsweep-<env>-<suffix>` with RBAC authorisation. The runner identity
  `id-pvsweep-<env>-runner` is Key Vault Secrets User; `principalId` from the parameters file is
  Key Vault Secrets Officer.
- AcrPull on the registry for the runner identity.
- Container Apps environment `cae-pvsweep-<env>`. It is consumption-only (no workload profiles), so you
  pay only while an execution runs.
- Job `job-pvsweep-<env>-sweep`:
  - Runs as the runner identity and pulls `<registry>/pvsweep-runner:<tag>` with that identity.
  - 0.5 CPU and 1 GiB, one replica, no retries, 6 h timeout.
  - Two Key Vault-backed secrets, each resolved through the identity (`keyVaultUrl` + `identity`):
    - `snowflake-runner-key`, exposed as `PVSWEEP_SNOWFLAKE_PRIVATE_KEY` (store, user PVSWEEP_RUNNER).
    - `snowflake-agent-key`, exposed as `PVSWEEP_SNOWFLAKE_AGENT_PRIVATE_KEY` (in-process agent, user PVSWEEP_AGENT).
  - `PVSWEEP_SNOWFLAKE_USER` is deliberately not set: both code paths read it, and each defaults to its own user.
  - Plain environment variables: `AZURE_CLIENT_ID` (for `DefaultAzureCredential`), `PVSWEEP_FOUNDRY_ACCOUNT`,
    `PVSWEEP_PROJECT_ENDPOINT`, `PVSWEEP_SNOWFLAKE_ACCOUNT`, `PVSWEEP_PROVIDER` (default `gpt`),
    `PVSWEEP_GPT_SMALL/LARGE`, `PVSWEEP_CLAUDE_SMALL/LARGE`, `PVSWEEP_PROMPTS_DIR`. Empty values are left out.
  - Default command: a small shell wrapper picks the provider and its deployments, then runs
    `python -I -m pvsweep_runner sweep --provider <p> --small <small> [--large <large>] <args>`.
    - The provider comes from `PVSWEEP_PROVIDER`, or from `--provider` in the arguments.
    - `gpt` uses the GPT deployments; `claude` uses the Claude small and large deployments.
    - Default args are `--backend snowflake --match agent --concurrency 2`, with no limit.
    - Arguments passed at start time replace the default args, and come last, so they win.
- Optional load job (`deployLoadJob=true`), off by default.

The image (`runner/Dockerfile`) installs the runner in editable mode under `/app/runner` with `prompts/` at
`/app/prompts`. That is where `steps.py` and `__main__.py` look for prompts (`parents[2]`). The build
fails if a prompt is not found.

## Order (first time)

The job's secret references must point at secrets that exist, so the first deployment skips the jobs:

```sh
make build-runner                          # image pvsweep-runner:<git short sha> in the registry
make deploy DEPLOY_RUNNER=1 RUNNER_JOBS=0  # Key Vault, monitoring, roles; no environment or jobs yet
make kv-secrets                            # .secrets/snowflake_{runner,agent}.p8 -> Key Vault (--file, retries on 403)
make deploy DEPLOY_RUNNER=1                # Container Apps environment and the sweep job
make run-sweep-job                         # one small execution (see below)
```

Later image updates: `make build-runner && make deploy DEPLOY_RUNNER=1`. Pass the same `IMAGE_TAG=` to both
when the tag is not the current commit.

A plain `make deploy` (without `DEPLOY_RUNNER=1`) leaves the runner resources in place, because
deployments are incremental. Its outputs then have an empty `KEYVAULTNAME` and `SWEEPJOBNAME`, so run
`make deploy DEPLOY_RUNNER=1` again before `kv-secrets` or `run-sweep-job`. `make outputs` reads only the
latest successful deployment.

## Run and read logs

```sh
make run-sweep-job                                   # --limit 6 --concurrency 2 --match agent --backend snowflake --provider gpt
make run-sweep-job SWEEP_ARGS="--limit 20 --provider claude"
```

`scripts/run_sweep_job.sh` uses only the core az CLI:

1. It reads the job template.
2. It starts an execution through the ARM `start` API with the same template and only `args` replaced, so
   the environment variables and secret references are kept.
3. It checks that the execution received the override. If it did not, it stops the execution.
4. It polls the execution until it finishes.
5. It prints the console logs from Log Analytics (`ContainerAppConsoleLogs_CL`), retrying while ingestion
   catches up (typically 2 to 5 minutes).

It refuses to start without `--limit` unless `ALLOW_FULL_SWEEP=1`.

Check the result in Snowflake:

```sh
snow sql -c pvsweep -q "select run_id, provider, status, counts from PVSWEEP.SWEEP.RUN order by started_at desc limit 3"
```

Once an execution has ended, `az containerapp job logs show` answers "No replicas found for execution";
use Log Analytics, which lags a few minutes behind the run. Lines with the same timestamp may come back
out of order.

Ad hoc log query (workspace id in `.env.<env>` as `LOGANALYTICSWORKSPACEID`):

```kusto
ContainerAppConsoleLogs_CL | where ContainerJobName_s == 'job-pvsweep-dev-sweep' | order by TimeGenerated desc | take 200
```

## Cost notes

- Consumption environment, 0.5 vCPU / 1 GiB, billed per second only while an execution runs. A 6-record
  run takes about 3 minutes (unverified: whether the consumption free grant fully covers such runs).
- Most of the cost is model tokens (Foundry) and Snowflake warehouse time, not the job itself.
- Log Analytics is pay-per-GB ingested, with 30 days retention. Console logs of a sweep are small.
- Key Vault standard is charged per operation; the secret references are read by the platform (frequency not measured).
- The 50 EUR monthly budget in `infra/main.bicep` is filtered on the resource group, so it covers all of the above.
- Default args have no `--limit`: a started job with default args sweeps the whole corpus.
