# Pharmacovigilance Sweep

A proof of concept that re-screens a pharmaceutical company's **non-pharmacovigilance** records
(medical information logs, field-force CRM notes, patient support programme notes, product quality
complaints, social listening) for adverse events that never reached the pharmacovigilance department,
and reconciles what vendors say they forwarded against what pharmacovigilance received.

Models propose; a person decides. Every routed record ends as a prioritised finding with a proposed
case intake package, and a reviewer confirms day 0, the outcome and the compliance findings in a
review app. Public and synthetic data only; not a validated system.

Built on **Microsoft Foundry** (GPT and Claude models, hosted matching agents, content filters,
evaluations) over a data platform that can be **Snowflake** or **Azure Databricks**: the same tables,
runner, agents, prompts, evaluation and review app run on both. Everything is deployed from scratch
by the scripts in this repository.

- What it does and why: [docs/poc-definition.md](docs/poc-definition.md)
- How it is built: [docs/architecture.md](docs/architecture.md)
- What it is worth and what it costs: [docs/business-case.md](docs/business-case.md)
- What was verified, with numbers: [docs/ops/spike-log.md](docs/ops/spike-log.md)
- Provider comparison on 450 records: [docs/ops/comparison-round3.md](docs/ops/comparison-round3.md)
- Snowflake setup: [docs/ops/snowflake-setup.md](docs/ops/snowflake-setup.md) ·
  Databricks: [docs/ops/databricks.md](docs/ops/databricks.md) ·
  Unattended runs: [docs/ops/runner-job.md](docs/ops/runner-job.md)

## Results in one table

450 synthetic records across five channels, screening and extraction on the small model, matching by
an agent on the large model with read-only tools over the safety database, intake queue and vendor
log (round 3; details and caveats in the spike log and the business case).

| | GPT (`gpt-5-4-mini`) | Claude (Haiku 5.5 + Sonnet 5.5 agent, on Foundry) |
|---|---|---|
| Screening recall / precision | 0.997 / 1.0 | 0.976 / 0.997 |
| Extraction valid | 0.995 | 1.0 |
| Causality statement | 0.901 | 0.938 |
| Matching outcome | 0.835 | 0.954 |
| Model cost per sweep | about $11 | about $11 |

The hosted agents, the review app and the unattended job were verified on Snowflake and on
Databricks with 8-record samples; the Databricks copy holds the results copied from Snowflake, not
recomputed.

## Layout

```
infra/          Bicep: Foundry resource, project and model deployments, budget, registry, identities,
                Key Vault and Container Apps job, project connections, Databricks workspace
agent/          Hosted matching agent image (Microsoft Agent Framework, Invocations protocol)
runner/         Python: data staging (pvsweep_load), synthetic data (pvsweep_synth), sweep runner
                (pvsweep_runner: local DuckDB, Snowflake and Databricks backends), matching agent
                package (pvsweep_agent), tests
prompts/        Versioned prompts and JSON schemas for screening, extraction and matching
snowflake/      Bootstrap, versioned migrations, load script, Streamlit review app
databricks/     The same platform for Unity Catalog: bootstrap, migrations, load, review app
config/         Fictional brands of the fictional marketing authorisation holder
data/synthetic/ Committed synthetic records and their ground truth (scenario-first)
data/eval/      Exports graded by the Foundry evaluators
scripts/        Deployment helpers: hosted agents, Key Vault secrets, job runs, Snowflake and
                Databricks setup, migrations, loads, result sync, review apps
docs/           Definition, architecture, business case, operational notes
Makefile        One target per step; `make -n <target>` shows the command
```

## Deploy from scratch

Prerequisites: Azure CLI logged in with Owner on a pay-as-you-go subscription, `uv`, Snowflake CLI
and a Snowflake account in an EU region (any cloud), or a Databricks workspace which `make deploy`
can create. Secrets never enter the repository: Snowflake keys live in `.secrets/` (git-ignored) and
reach Azure through Key Vault and a Foundry project connection; connection ids live in `.env`.

```bash
cp infra/main.parameters.json infra/main.parameters.local.json   # fill in your values
make deploy             # Azure: Foundry, models, budget, registry, identities (Sweden Central)
make build-agent        # agent image into the registry
make deploy-agents      # hosted matching agents (GPT and Claude) in Foundry Agent Service
make snow-bootstrap     # once, as ACCOUNTADMIN: roles, warehouse, database, service users
make snow-migrate       # schemas, tables, views, grants
make snow-load          # public datasets -> Parquet -> Snowflake
make snow-app           # Streamlit review app in Snowflake
```

Optional: `make deploy DEPLOY_RUNNER=1`, `make kv-secrets` and `make run-sweep-job` run the sweep as
an Azure Container Apps job; `make deploy DEPLOY_DATABRICKS=1` followed by the `dbx-*` targets sets up
the Databricks platform and copies the processed results from Snowflake. `make teardown` removes
everything in Azure.

## Run locally without a cloud data platform

The runner has a DuckDB backend over the staged Parquet files and the committed synthetic data; the
models still run on Foundry:

```bash
make stage-data
uv run --project runner python -I -m pvsweep_runner sweep --account <foundry-account> \
  --project-endpoint https://<foundry-account>.services.ai.azure.com/api/projects/<project> \
  --provider gpt --small gpt-5-4-mini --match agent --limit 40
```

`--backend snowflake` or `--backend databricks` runs the same sweep on the cloud platform;
`--match hosted` uses the hosted agents instead of the in-process one. `--provider claude-direct`
uses the Anthropic API with `ANTHROPIC_API_KEY` from `.env` (development only; the evaluated path is
Claude on Foundry). Evaluate a run with `python -I -m pvsweep_runner.evaluate --db <file>` and compare
two runs with `pvsweep_runner.compare`; `pvsweep_runner.snapshot` copies a cloud run into a local file.

## Development

```bash
cd runner && uv sync && uv run pytest -q && uv run ruff check .
```

CI runs the tests and lint on every push; the deployment workflow is manual and uses OIDC, with the
parameters file as the only secret.

## Data and licences

FAERS (CC0) and VAERS (CC0 / Apache 2.0) are downloaded at load time at pinned revisions and never
committed. MedDRA and the EMA IME list are bring-your-own files; demo mode uses a term vocabulary
derived from the public data and a short project-defined serious-event list, neither presented as
the licensed artefacts. Brand names are fictional (checked against the Spanish and EU registers).

## Licence

MIT (see LICENSE).
