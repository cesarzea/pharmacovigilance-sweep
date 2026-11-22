# Pharmacovigilance Sweep

A proof of concept that re-screens a pharmaceutical company's **non-pharmacovigilance** records
(medical information logs, field-force CRM notes, patient support programme notes, product quality
complaints, social listening) for adverse events that never reached the pharmacovigilance department,
and reconciles what vendors say they forwarded against what pharmacovigilance received.

Built on **Snowflake** (data, results, review app) and **Microsoft Foundry** (GPT and Claude models,
a hosted matching agent, guardrails, evaluations), deployable from scratch with the scripts in this
repository. Public and synthetic data only; not a validated system.

- What it does and why: [docs/poc-definition.md](docs/poc-definition.md)
- How it is built: [docs/architecture.md](docs/architecture.md)
- Spike results and operational notes: [docs/ops/](docs/ops/)

## Layout

```
infra/          Bicep: Foundry resource and project, model deployments, budget, registry, identities
agent/          Hosted matching agent image (Microsoft Agent Framework, Invocations protocol)
runner/         Python: data staging (pvsweep_load), synthetic data (pvsweep_synth),
                sweep runner (pvsweep_runner), matching agent package (pvsweep_agent), tests
prompts/        Versioned prompts and JSON schemas for screening, extraction and matching
snowflake/      Bootstrap, versioned migrations, load script
config/         Fictional brands of the fictional MAH
data/synthetic/ Committed synthetic records and their ground truth (scenario-first)
scripts/        Deployment helpers (hosted agents, Snowflake keys, migrations, loads)
Makefile        deploy, build-agent, deploy-agents, stage-data, snow-*, teardown
```

## Deploy from scratch

Prerequisites: Azure CLI (logged in, Owner on a pay-as-you-go subscription), `uv`, Snowflake CLI, a
Snowflake trial account (Enterprise, Azure, EU region). One-time manual steps are listed in
[docs/ops/snowflake-setup.md](docs/ops/snowflake-setup.md).

```bash
cp infra/main.parameters.json infra/main.parameters.local.json   # fill in your values
make deploy            # Azure: Foundry, models, budget, registry, identities (Sweden Central)
make build-agent       # agent image into the registry
make deploy-agents     # hosted matching agent(s) in Foundry Agent Service
make snow-bootstrap    # once, as ACCOUNTADMIN
make snow-migrate      # schemas, tables, views, grants
make snow-load         # public datasets -> Parquet -> Snowflake
make teardown          # removes everything in Azure
```

## Run locally without Snowflake

The runner has a DuckDB backend over the staged Parquet files and the committed synthetic data:

```bash
make stage-data
uv run --project runner python -I -m pvsweep_synth plan
uv run --project runner python -I -m pvsweep_runner sweep --account <foundry-account> \
  --project-endpoint https://<foundry-account>.services.ai.azure.com/api/projects/<project> \
  --provider gpt --small gpt-5-4-mini --large gpt-5-4-mini --match agent --limit 40
```

`--provider claude-direct` uses the Anthropic API with `ANTHROPIC_API_KEY` from a git-ignored `.env`
(development only; the evaluated path is Claude on Foundry).

## Status

See [docs/ops/spike-log.md](docs/ops/spike-log.md). Claude deployments wait on a Foundry quota
request (support ticket in [docs/ops/claude-quota-request.md](docs/ops/claude-quota-request.md)).

## Data and licences

FAERS (CC0) and VAERS (CC0 / Apache 2.0) are downloaded at load time at pinned revisions and never
committed. MedDRA and the EMA IME list are bring-your-own files; demo mode uses a term vocabulary
derived from the public data and a short project-defined serious-event list, neither presented as
the licensed artefacts.

## Licence

MIT (see LICENSE).
